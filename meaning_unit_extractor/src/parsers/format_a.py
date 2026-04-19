"""
格式 A 解析器：姓名(HH:MM:SS): 正文

示例：
    李明(00:05:33): 那么我们接下来就正式开始这个咨询...

典型来源：带说话人分离的 ASR 原始输出（飞书、腾讯会议、讯飞听见等）。
此格式下 ASR 常把连续发言按呼吸停顿切成多轮（同人伪轮次），脚本会在后续重建阶段合并。
"""
from __future__ import annotations
import re
from ..models import CanonicalTurn


SPEAKER_RE = re.compile(
    r"^(?P<speaker>[\u4e00-\u9fa5A-Za-z]{1,10})"
    r"\((?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?\)"
    r"[:：]\s*(?P<text>.*)$"
)


def _hms_to_seconds(h: int, m: int, s: int) -> int:
    return h * 3600 + m * 60 + s


def parse_format_a(text: str, filename: str) -> tuple[list[CanonicalTurn], dict]:
    """
    解析格式 A。返回 (turns, header_metadata)。
    header_metadata 通常为空（该格式不含头部元数据）。
    """
    turns: list[CanonicalTurn] = []
    file_stem = filename.rsplit(".", 1)[0]

    # 预处理：按空行分段，支持「标签行 + 正文行」跨行的情况
    paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()
    ]

    idx = 0
    for para in paragraphs:
        # 某些文件里，标签与正文在同一行；统一用 SPEAKER_RE 匹配第一行
        first_line, _, rest = para.partition("\n")
        m = SPEAKER_RE.match(first_line.strip())
        if not m:
            # 不是对话段，跳过（可能是额外的说明性段落）
            continue

        speaker = m.group("speaker")
        h = int(m.group("h"))
        mi = int(m.group("m"))
        s = int(m.group("s") or 0)
        # 轮次文本 = 首行标签后的残余 + 后续行
        parts = [m.group("text")]
        if rest:
            parts.append(rest)
        body = "\n".join(parts).strip()

        turn_id = f"{file_stem}_t{idx:04d}"
        ts_raw = f"{h:02d}:{mi:02d}:{s:02d}"
        turns.append(CanonicalTurn(
            turn_id=turn_id,
            source_file=filename,
            source_format="A_timestamped_name",
            turn_index=idx,
            speaker_raw=speaker,
            speaker_role="",                  # 角色由推断层后续填入
            speaker_stable_id=speaker,
            timestamp_raw=ts_raw,
            timestamp_seconds=_hms_to_seconds(h, mi, s),
            text=body,
        ))
        idx += 1

    header_metadata = {}
    return turns, header_metadata
