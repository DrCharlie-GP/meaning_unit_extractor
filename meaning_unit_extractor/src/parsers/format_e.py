"""
格式 E 解析器：纯自述/日记/独白文本（单一说话人，无标签）。

典型来源：
  - 日记法（diary study）研究
  - 自传体访谈、叙事访谈转录（仅保留受访者发言部分）
  - 开放式问卷的长文本答题
  - 健康博客、患者自述等长文本

切分策略：按空行分隔的段落生成 CanonicalTurn；若全文无空行，则作为单一轮次。
说话人标签默认为"自述者"，可通过 CLI `--speaker-label` 覆盖。
角色固定为 primary_informant。

本格式不做自动检测，必须通过 CLI `--format monologue` 显式声明，
避免把"漏标签的访谈"误判为自述文本。
"""
from __future__ import annotations
import re
from ..models import CanonicalTurn


def parse_format_e(
    text: str,
    filename: str,
    speaker_label: str = "自述者",
) -> tuple[list[CanonicalTurn], dict]:
    """
    解析纯自述文本。返回 (turns, header_metadata)。
    header_metadata 始终为空（此格式不含头部元数据；
    日记日期等请在后处理阶段另行处理）。
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
            source_format="E_monologue",
            turn_index=idx,
            speaker_raw=speaker_label,
            speaker_role="primary_informant",
            speaker_stable_id=speaker_label,
            text=body,
        ))
        idx += 1

    return turns, {}
