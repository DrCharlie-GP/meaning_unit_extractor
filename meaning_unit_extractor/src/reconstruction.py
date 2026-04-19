"""
轮次重建层：在意义单元切分之前做两件事：
  1. 同说话人连续 ASR 轮次合并（呼吸停顿被误判为说话人变更）
  2. 短访谈员回应（backchannel）穿透合并（受访者发言被短 "明白/对" 打断但实际未停）

仅在带时间戳的格式（A / D）上有意义；格式 B 因已人工编辑，默认跳过。
"""
from __future__ import annotations
from .models import CanonicalTurn


def _is_backchannel(turn: CanonicalTurn, max_chars: int, words: list[str]) -> bool:
    text = turn.text.strip()
    if len(text) > max_chars:
        return False
    # 清除标点后检查
    bare = "".join(ch for ch in text if ch.isalnum())
    if not bare:
        return False
    # 若整条发言由若干已知应答词串联而成，视为 backchannel
    for w in words:
        if w and w in text:
            return True
    return False


def merge_same_speaker_and_backchannel(
    turns: list[CanonicalTurn],
    gap_threshold_seconds: int,
    backchannel_enabled: bool,
    backchannel_words: list[str],
    backchannel_max_chars: int,
    interviewer_roles: tuple[str, ...] = ("interviewer",),
) -> list[CanonicalTurn]:
    """
    合并相邻同说话人轮次，并在允许的情况下跨越 backchannel 合并。
    返回新的 CanonicalTurn 列表，原 turns 不被修改。

    合并规则：
      - 同说话人相邻，且时间间隔 <= gap_threshold → 合并
      - 格式 B（无时间戳）视每个相邻同说话人轮次默认可合并
      - A 位两个受访者轮次之间夹着一条短 backchannel 访谈员轮次时，
        若时间间隔 <= 30s 且 backchannel_enabled，跨越合并
    """
    if not turns:
        return []

    out: list[CanonicalTurn] = []
    i = 0
    while i < len(turns):
        base = turns[i]
        merged_ids = []
        combined_text = base.text
        last_ts = base.timestamp_seconds

        j = i + 1
        while j < len(turns):
            cur = turns[j]

            # 情况 1：同说话人直接相邻
            if cur.speaker_raw == base.speaker_raw:
                gap = (cur.timestamp_seconds - last_ts
                       if last_ts is not None and cur.timestamp_seconds is not None
                       else 0)
                if (last_ts is None
                        or cur.timestamp_seconds is None
                        or gap <= gap_threshold_seconds):
                    merged_ids.append(cur.turn_id)
                    combined_text += " " + cur.text
                    last_ts = cur.timestamp_seconds if cur.timestamp_seconds is not None else last_ts
                    j += 1
                    continue
                else:
                    break

            # 情况 2：相邻是 backchannel 访谈员短轮次，且 j+1 仍是同说话人
            if (backchannel_enabled
                    and cur.speaker_role in interviewer_roles
                    and _is_backchannel(cur, backchannel_max_chars, backchannel_words)
                    and j + 1 < len(turns)
                    and turns[j + 1].speaker_raw == base.speaker_raw):
                nxt = turns[j + 1]
                gap = (nxt.timestamp_seconds - last_ts
                       if last_ts is not None and nxt.timestamp_seconds is not None
                       else 0)
                if (last_ts is None
                        or nxt.timestamp_seconds is None
                        or gap <= 30):
                    # 跨越 backchannel 合并 base 与 nxt
                    merged_ids.append(cur.turn_id)    # backchannel 也记入
                    merged_ids.append(nxt.turn_id)
                    combined_text += " " + nxt.text
                    last_ts = nxt.timestamp_seconds if nxt.timestamp_seconds is not None else last_ts

                    # 把 backchannel 作为单独输出轮次保留（打标）
                    bc = _clone_with_flag(cur, "bridged_by_merge")
                    out.append(bc)
                    j += 2
                    continue
                else:
                    break

            break

        if merged_ids:
            # 用合并后的文本更新 base，保留首个 turn 的 ID 与时间戳
            merged_turn = _clone_with_merged(base, combined_text, merged_ids)
            out.append(merged_turn)
        else:
            out.append(base)
        i = j if j > i else i + 1

    return out


def _clone_with_flag(turn: CanonicalTurn, flag: str) -> CanonicalTurn:
    import dataclasses
    new = dataclasses.replace(turn, flags=list(turn.flags) + [flag])
    return new


def _clone_with_merged(
    base: CanonicalTurn,
    new_text: str,
    merged_ids: list[str],
) -> CanonicalTurn:
    import dataclasses
    return dataclasses.replace(
        base,
        text=new_text.strip(),
        merged_from_asr_turns=[base.turn_id] + list(merged_ids),
    )
