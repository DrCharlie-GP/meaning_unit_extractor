"""
格式 D 解析器：说话人 N MM:SS（带说话人分离的 ASR 工具输出）

示例：
    2024年9月13日 下午 4:22|23分钟 55秒

    关键词:
    社区、医院、活动、高血压、糖尿病...

    文字记录:

    说话人 1 00:02

    您平时去那个社区卫生服务中心看病吗？

    说话人 2 00:06

    嗯，去他那个校医院，基本在那。

特征：匿名说话人编号（说话人 1/2/3/未知），MM:SS 时间戳独占一行，文本在下一段。
首部可能含日期、时长、关键词段。
"""
from __future__ import annotations
import re
from ..models import CanonicalTurn


# 标签行：「说话人 1 00:02」或「未知 00:55」
SPEAKER_LINE_RE = re.compile(
    r"^(?P<speaker>说话人\s+\d+|未知)\s+(?P<m>\d{1,2}):(?P<s>\d{2})\s*$"
)

# 文件头部探针
HEADER_DATE_RE = re.compile(
    r"^(?P<date>\d{4}年\d{1,2}月\d{1,2}日)"
    r"(?:\s*(?P<ampm>下午|上午))?"
    r"(?:\s*(?P<clock>\d{1,2}:\d{2}))?"
    r"(?:\s*\|\s*(?P<duration>\d+分钟\s*\d+秒))?"
)
KEYWORD_MARKER_RE = re.compile(r"^\*{0,2}关键词\*{0,2}[:：]?\s*$")
TRANSCRIPT_MARKER_RE = re.compile(r"^文字记录[:：]?\s*$")


def _mmss_to_seconds(m: int, s: int) -> int:
    return m * 60 + s


def _parse_header(lines: list[str]) -> tuple[dict, int]:
    """
    解析可能存在的头部元数据（日期时间、关键词列表）。
    返回 (metadata, consumed_line_index) —— 从 consumed_line_index 起开始读轮次。
    """
    metadata = {}
    i = 0
    in_keyword_section = False
    keyword_buffer: list[str] = []

    while i < len(lines):
        ln = lines[i].strip()

        # 遇到第一行说话人标签，头部扫描结束
        if SPEAKER_LINE_RE.match(ln):
            break

        if not ln:
            i += 1
            continue

        # 日期时间行
        m = HEADER_DATE_RE.match(ln)
        if m and not metadata.get("date"):
            metadata.update({k: v for k, v in m.groupdict().items() if v})
            i += 1
            continue

        # 关键词段
        if KEYWORD_MARKER_RE.match(ln):
            in_keyword_section = True
            i += 1
            continue

        if TRANSCRIPT_MARKER_RE.match(ln):
            in_keyword_section = False
            i += 1
            continue

        if in_keyword_section:
            keyword_buffer.append(ln)
            i += 1
            continue

        # 未识别的头部行 —— 可能是额外说明；保存但不阻断
        i += 1

    if keyword_buffer:
        kws = " ".join(keyword_buffer)
        kws = re.sub(r"[、,，\s]+", ",", kws).strip(",")
        metadata["keywords"] = [k for k in kws.split(",") if k]

    return metadata, i


def parse_format_d(text: str, filename: str) -> tuple[list[CanonicalTurn], dict]:
    turns: list[CanonicalTurn] = []
    file_stem = filename.rsplit(".", 1)[0]

    raw_lines = text.split("\n")
    header_metadata, start_idx = _parse_header(raw_lines)

    # 主体：交替出现「标签行」「（空行）」「文本行（可能多行）」「空行」...
    # 策略：遍历行，遇到标签行则开始新轮次，其后所有非标签非空内容都属于该轮次，直到下一标签行。
    idx = 0
    i = start_idx
    while i < len(raw_lines):
        ln = raw_lines[i].strip()
        m = SPEAKER_LINE_RE.match(ln)
        if not m:
            i += 1
            continue

        speaker_raw = m.group("speaker")
        mi = int(m.group("m"))
        s = int(m.group("s"))

        # 收集正文：自下一行起，直到下一个标签行或文件结束
        body_lines = []
        j = i + 1
        while j < len(raw_lines):
            nxt = raw_lines[j].strip()
            if SPEAKER_LINE_RE.match(nxt):
                break
            if nxt:
                body_lines.append(nxt)
            j += 1

        body = " ".join(body_lines).strip()
        if body:
            turn_id = f"{file_stem}_t{idx:04d}"

            # 未知 → role 直接定为 unknown；其余由推断层处理
            role = "unknown" if speaker_raw == "未知" else ""

            turns.append(CanonicalTurn(
                turn_id=turn_id,
                source_file=filename,
                source_format="D_numeric_speaker",
                turn_index=idx,
                speaker_raw=speaker_raw,
                speaker_role=role,
                speaker_stable_id=speaker_raw,
                timestamp_raw=f"{mi:02d}:{s:02d}",
                timestamp_seconds=_mmss_to_seconds(mi, s),
                text=body,
            ))
            idx += 1

        i = j  # 跳到下一个标签行

    return turns, header_metadata
