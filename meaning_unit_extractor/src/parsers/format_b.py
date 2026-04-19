"""
格式 B 解析器：访谈者：/受访者： 正文

示例：
    2024.1.31 照顾者A，认知障碍老人为其母亲

    访谈者：刚才您说差不多去两年前两月份的时候...

    受访者：对啊，

典型来源：人工编辑过的访谈转录。
特征：首行可能含元数据（日期、受访者编号、关系等）；
正文中可能含方括号研究者注释（如"[说明：这里是研究者补充的背景信息]"）。
"""
from __future__ import annotations
import re
from ..models import CanonicalTurn


# 规范角色词表及其映射
ROLE_MAP = {
    "访谈者": "interviewer",
    "访谈员": "interviewer",
    "研究者": "interviewer",
    "问": "interviewer",
    "受访者": "primary_informant",
    "被访者": "primary_informant",
    "照顾者": "primary_informant",
    "答": "primary_informant",
}

SPEAKER_RE = re.compile(
    r"^(?P<speaker>访谈者|访谈员|研究者|受访者|被访者|照顾者|问|答)"
    r"[:：]\s*(?P<text>.*)$"
)

# 首行元数据探针
HEADER_PATTERNS = [
    re.compile(
        r"^(?P<date>\d{4}[\.\-/]\d{1,2}[\.\-/]\d{1,2})"
        r"[\s,，]+照顾者\s*(?P<caregiver>[^\s,，]+)"
        r"(?:[,，\s]*(?:认知障碍老人|患者)\s*(?:为其)?\s*(?P<relation>[^\s,，]+))?"
    ),
]

ANNOTATION_RE = re.compile(r"\[([^\]]+)\]")


def _extract_annotations(text: str) -> tuple[str, list[dict]]:
    """
    从文本中抽取方括号研究者注释。原文保留（含方括号），但额外返回结构化列表。
    """
    annotations = []
    for m in ANNOTATION_RE.finditer(text):
        annotations.append({
            "type": "editorial",
            "content": m.group(1),
            "char_offset": m.start(),
        })
    return text, annotations


def _parse_header(lines: list[str]) -> tuple[dict, int]:
    """
    尝试从前若干行提取元数据。
    返回 (metadata, consumed_lines) —— 消耗的行数供上层跳过。
    """
    metadata = {}
    for i, ln in enumerate(lines[:5]):
        stripped = ln.strip()
        if not stripped:
            continue
        for pat in HEADER_PATTERNS:
            m = pat.match(stripped)
            if m:
                metadata.update({k: v for k, v in m.groupdict().items() if v})
                return metadata, i + 1
        # 首个非空行不是元数据也不是对话，继续扫
        if SPEAKER_RE.match(stripped):
            return metadata, i   # 遇到首个说话人行，停止头部扫描
    return metadata, 0


def parse_format_b(text: str, filename: str) -> tuple[list[CanonicalTurn], dict]:
    turns: list[CanonicalTurn] = []
    file_stem = filename.rsplit(".", 1)[0]

    raw_lines = text.split("\n")
    header_metadata, consumed = _parse_header(raw_lines)

    # 去首部元数据之后按空行分段
    remainder = "\n".join(raw_lines[consumed:])
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", remainder) if p.strip()]

    idx = 0
    for para in paragraphs:
        first_line, _, rest = para.partition("\n")
        m = SPEAKER_RE.match(first_line.strip())
        if not m:
            continue

        speaker_word = m.group("speaker")
        body_parts = [m.group("text")]
        if rest:
            body_parts.append(rest)
        body = "\n".join(body_parts).strip()

        body, annotations = _extract_annotations(body)

        role = ROLE_MAP.get(speaker_word, "unknown")

        turn_id = f"{file_stem}_t{idx:04d}"
        turns.append(CanonicalTurn(
            turn_id=turn_id,
            source_file=filename,
            source_format="B_semantic_role",
            turn_index=idx,
            speaker_raw=speaker_word,
            speaker_role=role,
            speaker_stable_id=speaker_word,
            text=body,
            annotations=annotations,
        ))
        idx += 1

    return turns, header_metadata
