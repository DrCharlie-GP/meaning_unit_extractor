"""
启发式参数推断层。

职责：基于已解析的 CanonicalTurn 列表，自动推断运行时参数，写入 detected_config。
所有推断都是可解释的规则，结果记入 audit_report 的"参数推断溯源"节。

推断项：
  - speaker_role_map   每个 speaker_raw 到规范角色的映射
  - max_length         基于小句长度分布的 95 百分位校准
  - gap_threshold      同说话人连续轮次时间间隔的 95 百分位
  - vignette_enable    是否启用情境朗读检测
  - asr_noise_enable   是否启用 ASR 噪声过滤
"""
from __future__ import annotations
import re
from collections import defaultdict, Counter

from .models import CanonicalTurn


def _percentile(values: list[float], p: float) -> float:
    """纯 Python 的分位数计算，避免引入额外依赖。"""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _english_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    eng = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    total = sum(1 for ch in text if not ch.isspace())
    return eng / total if total else 0.0


def infer_speaker_roles(
    turns: list[CanonicalTurn],
    format_code: str,
    base_config: dict,
) -> tuple[dict, list[dict]]:
    """
    启发式推断每个说话人的规范角色。
    返回 (role_map, per_speaker_stats)。

    对格式 B：已在解析时按角色词填好，直接返回。
    对格式 A：若 speaker_raw 命中 known_interviewer_names 则定 interviewer；
             其余按启发式评分（问号率、长度反向、总字符反向）。
    对格式 D：纯启发式。"未知"固定映射为 unknown。
    """
    # 按 speaker_raw 聚合
    by_speaker: dict[str, list[CanonicalTurn]] = defaultdict(list)
    for t in turns:
        by_speaker[t.speaker_raw].append(t)

    # 格式 E（自述/日记）与格式 F（叙事民族志）都是单一说话人场景，
    # 解析阶段已把角色固定为 primary_informant，这里直接汇总返回。
    if format_code in ("E_monologue", "F_narrative"):
        role_map = {}
        stats = []
        for spk, ts in by_speaker.items():
            role = ts[0].speaker_role or "primary_informant"
            role_map[spk] = role
            stats.append({
                "speaker_raw": spk,
                "turns": len(ts),
                "total_chars": sum(len(t.text) for t in ts),
                "question_mark_ratio": 0.0,
                "avg_chars": sum(len(t.text) for t in ts) / len(ts) if ts else 0,
                "inferred_role": role,
                "method": "preset_by_format",
            })
        return role_map, stats

    # 若是格式 B，解析阶段已定角色，直接汇总
    if format_code == "B_semantic_role":
        role_map = {}
        stats = []
        for spk, ts in by_speaker.items():
            role = ts[0].speaker_role or "unknown"
            role_map[spk] = role
            stats.append({
                "speaker_raw": spk,
                "turns": len(ts),
                "total_chars": sum(len(t.text) for t in ts),
                "question_mark_ratio": 0.0,   # 不参与评分
                "avg_chars": sum(len(t.text) for t in ts) / len(ts),
                "inferred_role": role,
                "method": "role_word_exact",
            })
        return role_map, stats

    # 格式 A / D 的启发式路径
    known_interviewers = set(base_config.get("known_interviewer_names", []))

    # 先处理「未知」特殊标签
    role_map = {}
    stats = []

    candidate_speakers = []
    for spk, ts in by_speaker.items():
        if spk == "未知":
            role_map[spk] = "unknown"
            stats.append({
                "speaker_raw": spk,
                "turns": len(ts),
                "total_chars": sum(len(t.text) for t in ts),
                "question_mark_ratio": 0.0,
                "avg_chars": 0,
                "inferred_role": "unknown",
                "method": "literal_match_unknown",
            })
            continue
        if spk in known_interviewers:
            role_map[spk] = "interviewer"
            stats.append({
                "speaker_raw": spk,
                "turns": len(ts),
                "total_chars": sum(len(t.text) for t in ts),
                "question_mark_ratio": sum(1 for t in ts if t.text.rstrip().endswith(("?", "？"))) / len(ts),
                "avg_chars": sum(len(t.text) for t in ts) / len(ts),
                "inferred_role": "interviewer",
                "method": "known_name_match",
            })
            continue
        candidate_speakers.append((spk, ts))

    if not candidate_speakers:
        return role_map, stats

    # 计算评分项
    cand_stats = []
    for spk, ts in candidate_speakers:
        n = len(ts)
        total_chars = sum(len(t.text) for t in ts)
        avg_chars = total_chars / n
        qmark = sum(1 for t in ts if t.text.rstrip().endswith(("?", "？"))) / n
        cand_stats.append({
            "speaker_raw": spk,
            "turns": n,
            "total_chars": total_chars,
            "avg_chars": avg_chars,
            "question_mark_ratio": qmark,
        })

    # interviewer 的启发式识别：问号率最高 + 轮次相对多 + 平均长度相对短
    # 我们用加权评分；权重来自 base_config.inference.speaker_role
    w = base_config.get("inference", {}).get("speaker_role", {})
    w_q = w.get("question_mark_weight", 0.5)
    w_len = w.get("length_weight", 0.3)
    w_tot = w.get("total_chars_weight", 0.2)

    max_q = max((c["question_mark_ratio"] for c in cand_stats), default=0) or 1
    max_avg = max((c["avg_chars"] for c in cand_stats), default=0) or 1
    max_tot = max((c["total_chars"] for c in cand_stats), default=0) or 1

    # interviewer 倾向：q 高、avg 低、total 低
    for c in cand_stats:
        c["interviewer_score"] = (
            w_q * (c["question_mark_ratio"] / max_q)
            + w_len * (1 - c["avg_chars"] / max_avg)
            + w_tot * (1 - c["total_chars"] / max_tot)
        )

    cand_stats.sort(key=lambda x: -x["interviewer_score"])

    # 若已经通过 known_interviewer_names 认定过访谈员，则候选不再竞选 interviewer —
    # 所有候选按字符数分配 primary_informant / other_participant
    already_has_interviewer = any(r == "interviewer" for r in role_map.values())

    if already_has_interviewer:
        cand_stats.sort(key=lambda x: -x["total_chars"])
        cand_stats[0]["inferred_role"] = "primary_informant"
        cand_stats[0]["method"] = "max_total_chars_given_known_interviewer"
        role_map[cand_stats[0]["speaker_raw"]] = "primary_informant"
        for c in cand_stats[1:]:
            role_map[c["speaker_raw"]] = "other_participant"
            c["inferred_role"] = "other_participant"
            c["method"] = "residual"
    else:
        # 无 known_interviewer —— 走纯启发式
        interviewer_spk = cand_stats[0]["speaker_raw"]
        role_map[interviewer_spk] = "interviewer"
        cand_stats[0]["inferred_role"] = "interviewer"
        cand_stats[0]["method"] = "heuristic_score"

        remaining = [c for c in cand_stats if c["speaker_raw"] != interviewer_spk]
        if remaining:
            remaining.sort(key=lambda x: -x["total_chars"])
            remaining[0]["inferred_role"] = "primary_informant"
            remaining[0]["method"] = "max_total_chars"
            role_map[remaining[0]["speaker_raw"]] = "primary_informant"
            for c in remaining[1:]:
                role_map[c["speaker_raw"]] = "other_participant"
                c["inferred_role"] = "other_participant"
                c["method"] = "residual"

    stats.extend(cand_stats)
    return role_map, stats


def infer_max_length(turns: list[CanonicalTurn], base_config: dict) -> tuple[int, dict]:
    """
    基于文件小句长度分布校准 max_length。
    方法：按「，。！？」切出小句，取所有小句长度的 95 百分位；
          若高于默认 max_length，上调到向上取 10 整的值（不超过 hard_max_length）；
          若低于默认，维持默认（不下调，避免过度拆分）。
    """
    default = base_config["segmentation"]["max_length"]
    hard_max = base_config["segmentation"]["hard_max_length"]

    all_clause_lens = []
    for t in turns:
        if t.speaker_role == "interviewer":
            continue  # 访谈员话语一般较短，不代表分析主体的长度特征
        clauses = re.split(r"[，。！？]", t.text)
        for c in clauses:
            c = c.strip()
            if c:
                all_clause_lens.append(len(c))

    if not all_clause_lens:
        return default, {"method": "fallback_default", "sample_size": 0}

    p95 = _percentile(all_clause_lens, 0.95)
    p50 = _percentile(all_clause_lens, 0.50)

    if p95 > default:
        inferred = min(int(((p95 // 10) + 1) * 10), hard_max)
        method = "upscale_by_p95"
    else:
        inferred = default
        method = "keep_default"

    return inferred, {
        "method": method,
        "clause_p50": round(p50, 1),
        "clause_p95": round(p95, 1),
        "sample_size": len(all_clause_lens),
    }


def infer_gap_threshold(turns: list[CanonicalTurn], base_config: dict) -> tuple[int, dict]:
    """
    基于同说话人连续轮次的时间间隔推断合并阈值。
    无时间戳时返回默认值。
    """
    default = base_config["same_speaker_merge"]["default_gap_seconds"]

    gaps = []
    for prev, cur in zip(turns, turns[1:]):
        if (prev.speaker_raw == cur.speaker_raw
                and prev.timestamp_seconds is not None
                and cur.timestamp_seconds is not None):
            gap = cur.timestamp_seconds - prev.timestamp_seconds
            if gap > 0:
                gaps.append(gap)

    if not gaps:
        return default, {"method": "fallback_default", "sample_size": 0}

    p95 = _percentile(gaps, 0.95)
    # 取 p95 与默认的较大者，保留合并的包容性
    inferred = max(int(p95), 30)
    return inferred, {
        "method": "p95_with_floor",
        "gap_p50": round(_percentile(gaps, 0.5), 1),
        "gap_p95": round(p95, 1),
        "sample_size": len(gaps),
    }


def infer_vignette_enable(turns: list[CanonicalTurn], base_config: dict) -> tuple[bool, dict]:
    """是否启用情境朗读检测：若访谈员有一条以上超长轮次且命中触发词，启用。"""
    triggers = base_config["vignette"]["trigger_terms"]
    min_chars = base_config["vignette"]["min_chars"]

    hits = 0
    for t in turns:
        if t.speaker_role != "interviewer":
            continue
        if len(t.text) >= min_chars and any(tr in t.text for tr in triggers):
            hits += 1

    enabled = hits >= 1
    return enabled, {
        "method": "trigger_hit_count",
        "hits": hits,
    }


def infer_asr_noise(turns: list[CanonicalTurn], base_config: dict) -> tuple[bool, dict]:
    """全文英文字符比超过阈值时启用 ASR 噪声过滤。"""
    threshold = base_config["asr_noise"]["global_english_ratio_flag"]
    total_chars = sum(len(t.text) for t in turns)
    total_eng = sum(sum(1 for ch in t.text if ("a" <= ch.lower() <= "z")) for t in turns)
    ratio = total_eng / total_chars if total_chars else 0
    enabled = ratio >= threshold
    return enabled, {
        "method": "global_english_ratio",
        "english_ratio": round(ratio, 4),
        "threshold": threshold,
    }


def run_full_inference(
    turns: list[CanonicalTurn],
    format_code: str,
    base_config: dict,
) -> dict:
    """
    运行全部启发式推断，返回 detected_config 字典。
    结构与 base_config 同构，便于后续 deep-merge。
    """
    role_map, role_stats = infer_speaker_roles(turns, format_code, base_config)
    max_len, max_len_info = infer_max_length(turns, base_config)
    gap, gap_info = infer_gap_threshold(turns, base_config)
    vig_enabled, vig_info = infer_vignette_enable(turns, base_config)
    noise_enabled, noise_info = infer_asr_noise(turns, base_config)

    detected = {
        "speaker_role_map": role_map,
        "segmentation": {
            "max_length": max_len,
        },
        "same_speaker_merge": {
            "default_gap_seconds": gap,
        },
        "vignette": {
            "enabled": vig_enabled,
        },
        "asr_noise": {
            "enabled": noise_enabled,
        },
    }
    provenance = {
        "speaker_roles": role_stats,
        "max_length": max_len_info,
        "gap_threshold": gap_info,
        "vignette": vig_info,
        "asr_noise": noise_info,
    }
    return {"detected": detected, "provenance": provenance}
