"""
意义单元切分核心算法。

策略：两阶段贪心合并。
  阶段 1：把轮次正文切成原子小句（按所有标点），保留每个原子的终止符信息。
  阶段 2：贪心合并相邻原子，边界判定考虑长度、终止符强度、语篇标记。

当前实现只做规则层（不依赖嵌入模型）。若 base_config.semantic_refine.enabled=True，
预留了语义精调钩子，但默认不启用 —— 避免强制依赖 sentence-transformers 并保持
完全可复现。
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from .models import CanonicalTurn, MeaningUnit


@dataclass
class Atom:
    text: str                # 原子正文（含前导/尾部标点？不含前导空白）
    term: str                # 终止符：。！？，或 EOT（轮次结束）
    char_start: int          # 在原轮次中的起始偏移
    char_end: int            # 在原轮次中的结束偏移（不含终止符）


ATOMS_SPLIT_RE = re.compile(r"[。！？，]")


def _split_to_atoms(text: str) -> list[Atom]:
    """把轮次正文切成原子小句，保留终止符与位置。"""
    atoms: list[Atom] = []
    start = 0
    for m in ATOMS_SPLIT_RE.finditer(text):
        end = m.start()
        t = text[start:end].strip()
        if t:
            atoms.append(Atom(text=t, term=m.group(), char_start=start, char_end=end))
        start = m.end()

    # 轮次末尾残余（无终止符）
    tail = text[start:].strip()
    if tail:
        atoms.append(Atom(text=tail, term="EOT", char_start=start, char_end=len(text)))
    return atoms


def segment_turn_to_units(
    turn: CanonicalTurn,
    seg_config: dict,
    discourse: dict,
) -> list[MeaningUnit]:
    """把单个轮次切成意义单元列表。"""
    min_len = seg_config["min_length"]
    max_len = seg_config["max_length"]
    strong_term = set(seg_config["strong_terminators"])
    weak_term = set(seg_config["weak_terminators"])
    continuation = tuple(discourse.get("continuation", []))
    contrast = tuple(discourse.get("contrast", []))

    atoms = _split_to_atoms(turn.text)
    if not atoms:
        return []

    units: list[MeaningUnit] = []
    buffer: list[Atom] = []
    file_stem = turn.source_file.rsplit(".", 1)[0]

    def flush(boundary_source: str):
        if not buffer:
            return
        combined_text = "".join(
            (a.text + (a.term if a.term not in ("EOT",) else ""))
            for a in buffer
        ).strip()
        # 去除尾部附加标点？保留更符合研究者阅读习惯
        unit_id = f"{file_stem}_u{len(units):04d}"
        cstart = buffer[0].char_start
        cend = buffer[-1].char_end
        units.append(MeaningUnit(
            unit_id=unit_id,
            source_file=turn.source_file,
            turn_id=turn.turn_id,
            unit_index_in_turn=len(units),
            speaker_raw=turn.speaker_raw,
            speaker_role=turn.speaker_role,
            speaker_stable_id=turn.speaker_stable_id,
            timestamp_seconds=turn.timestamp_seconds,
            text=combined_text,
            char_start_in_turn=cstart,
            char_end_in_turn=cend,
            length=len(combined_text),
            boundary_source=boundary_source,
            annotations=list(turn.annotations),
            flags=list(turn.flags),
        ))
        buffer.clear()

    for idx, atom in enumerate(atoms):
        buffer.append(atom)
        buf_len = sum(len(a.text) for a in buffer)

        at_strong = atom.term in strong_term
        at_eot = atom.term == "EOT"
        too_long = buf_len >= max_len
        long_enough = buf_len >= min_len

        # 判定是否可收束
        next_continues = False
        if idx + 1 < len(atoms):
            nxt = atoms[idx + 1].text
            if nxt.startswith(continuation) and not nxt.startswith(contrast):
                next_continues = True

        if too_long:
            flush("max_length_exceeded")
            continue
        if at_eot:
            flush("turn_end")
            continue
        if at_strong and long_enough and not next_continues:
            flush("strong_terminator")
            continue
        if atom.term in weak_term and buf_len >= max_len - 10 and not next_continues:
            # 逗号处的"柔性切分"—— 接近上限且不继续时切
            flush("weak_terminator_near_max")
            continue

    if buffer:
        flush("turn_tail")

    # 补充前后上下文
    for i, u in enumerate(units):
        if i > 0:
            u.preceding_context = units[i - 1].text[:80]
        if i + 1 < len(units):
            u.following_context = units[i + 1].text[:80]

    return units


def segment_all_turns(
    turns: list[CanonicalTurn],
    base_config: dict,
    effective_config: dict,
) -> list[MeaningUnit]:
    """对所有轮次做意义单元切分，按顺序返回。"""
    seg_config = {
        **base_config["segmentation"],
        **effective_config.get("segmentation", {}),
    }
    discourse = base_config["discourse_markers"]
    all_units: list[MeaningUnit] = []
    for t in turns:
        # vignette 朗读与 ASR 噪声轮次：仍切分但打标
        all_units.extend(segment_turn_to_units(t, seg_config, discourse))
    return all_units
