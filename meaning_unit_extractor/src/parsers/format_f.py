"""
格式 F 解析器：叙事民族志 / 田野笔记 / 学术散文。

与 Format E（单一说话人自述）的本质区别：
- Format E：全文由唯一说话人自述，所有命题都是该人的观点
- Format F：全文由研究者/作者讲述，但内含多重声音——
  研究者的观察、被访者的直接引语、护工等第三方的转述、
  研究者对现象的解释、一般性理论讨论

切分策略：与 Format E 相同——按空行分段产生 CanonicalTurn，
叙述者标签固定为 narrator_label（默认"研究者"）。

与 Format E 的区别体现在下游命题识别阶段：
LLM 收到 Format F 的轮次时使用专门的 narrative prompt，
产出的每条命题额外标注 subject（关于谁的情况）、
voice（谁说/报告/观察的）、layer（观察/引语/解释/理论）。

本格式不做自动检测，必须通过 CLI `--format narrative` 显式声明。
"""
from __future__ import annotations
import re
from ..models import CanonicalTurn


def parse_format_f(
    text: str,
    filename: str,
    narrator_label: str = "研究者",
) -> tuple[list[CanonicalTurn], dict]:
    """
    解析叙事民族志文本。返回 (turns, header_metadata)。
    header_metadata 为空字典（此格式不含头部元数据）。
    """
    turns: list[CanonicalTurn] = []
    file_stem = filename.rsplit(".", 1)[0]

    # 按空行分段
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    idx = 0
    for para in paragraphs:
        # 段内软换行合并为单行
        body = " ".join(ln.strip() for ln in para.split("\n") if ln.strip())
        if not body:
            continue

        turn_id = f"{file_stem}_t{idx:04d}"
        turns.append(CanonicalTurn(
            turn_id=turn_id,
            source_file=filename,
            source_format="F_narrative",
            turn_index=idx,
            speaker_raw=narrator_label,
            # 使用 primary_informant 保证能通过下游命题过滤（target_roles）；
            # 叙述者身份通过 speaker_raw 保留（默认"研究者"），
            # 下游 narrative prompt 会提示 LLM 认出研究者视角。
            speaker_role="primary_informant",
            speaker_stable_id=narrator_label,
            text=body,
        ))
        idx += 1

    return turns, {}
