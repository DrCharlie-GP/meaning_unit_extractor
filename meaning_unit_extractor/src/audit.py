"""
审计报告（audit_report.md）生成器。

报告结构：
  1. 参数推断溯源（最关键，供人工快速定位是否需要覆盖）
  2. 输入文件摘要（格式、长度、轮次数）
  3. 说话人与角色分布
  4. 轮次重建前后对比
  5. 意义单元产出统计（长度分布、边界来源分布、flag 分布）
  6. 需人工复核的条目清单
  7. LLM 调用记录（若有）
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
from statistics import median, mean

from .models import CanonicalTurn, MeaningUnit, Proposition


def _fmt_percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def generate_audit_report(
    input_filename: str,
    sniff_log: dict,
    format_detection,
    raw_turns: list[CanonicalTurn],
    reconstructed_turns: list[CanonicalTurn],
    units: list[MeaningUnit],
    propositions: list[Proposition],
    inference_result: dict,
    effective_config: dict,
    llm_trace: dict | None,
    proposition_trace: dict | None,
    output_dir: Path,
) -> None:

    lines = []
    lines.append(f"# 审计报告 — {input_filename}\n")
    lines.append("本报告由 meaning_unit_extractor 自动生成，供人工复核参数推断结果与切分质量。\n")

    # ---- 1. 参数推断溯源 ----
    lines.append("## 1. 参数推断溯源\n")
    lines.append(f"- 检测格式：`{format_detection.format_code}` "
                 f"（首命中行 {format_detection.first_match_line}）")
    hit_str = "、".join(f"{k}:{v}" for k, v in format_detection.hit_counts.items() if v > 0)
    lines.append(f"- 各格式命中计数：{hit_str}\n")

    # 说话人角色映射
    lines.append("### 说话人角色映射")
    role_map = effective_config.get("speaker_role_map", {})
    role_stats = inference_result.get("provenance", {}).get("speaker_roles", [])
    if role_stats:
        lines.append("| 原始标签 | 轮次数 | 平均字数 | 问号率 | 总字数 | 启发式角色 | 方法 |")
        lines.append("|---|---|---|---|---|---|---|")
        for st in role_stats:
            lines.append(
                f"| {st['speaker_raw']} | {st['turns']} | "
                f"{st['avg_chars']:.0f} | {st['question_mark_ratio']:.0%} | "
                f"{st['total_chars']} | `{st['inferred_role']}` | {st['method']} |"
            )
    lines.append("")

    if llm_trace and llm_trace.get("status") == "ok":
        lines.append("### LLM 复核结果")
        lines.append(f"- 模式：{llm_trace.get('mode')} / "
                     f"厂商：{llm_trace.get('provider')} / "
                     f"模型：{llm_trace.get('model')}")
        lines.append(f"- 调用延迟：{llm_trace.get('latency_ms')} ms")
        lines.append(f"- 置信度阈值：{llm_trace.get('confidence_threshold')}\n")
        lines.append("| 说话人 | 启发式 | LLM 判定 | 置信度 | 采纳 | 来源 |")
        lines.append("|---|---|---|---|---|---|")
        for d in llm_trace.get("per_speaker_decision", []):
            llm_info = d.get("llm") or {}
            llm_role = llm_info.get("role", "—") if llm_info else "—"
            llm_conf = f"{llm_info.get('confidence', 0):.2f}" if llm_info else "—"
            lines.append(
                f"| {d['speaker_raw']} | `{d.get('heuristic') or '—'}` | "
                f"`{llm_role}` | {llm_conf} | `{d['adopted']}` | {d['source']} |"
            )
        lines.append("")

        # 展示 LLM 给出的推理
        reasonings = []
        for d in llm_trace.get("per_speaker_decision", []):
            if d.get("llm"):
                r = d["llm"].get("reasoning", "").strip()
                if r:
                    reasonings.append(f"- **{d['speaker_raw']}**：{r}")
        if reasonings:
            lines.append("LLM 提供的判断理由：")
            lines.extend(reasonings)
            lines.append("")
    elif llm_trace:
        lines.append("### LLM 复核")
        lines.append(f"- 状态：`{llm_trace.get('status')}`；回退至启发式\n")

    # 其他推断项
    prov = inference_result.get("provenance", {})
    lines.append("### 其他推断参数")
    ml = prov.get("max_length", {})
    gap = prov.get("gap_threshold", {})
    vig = prov.get("vignette", {})
    noise = prov.get("asr_noise", {})
    lines.append(
        f"- `segmentation.max_length` = "
        f"{effective_config['segmentation']['max_length']} "
        f"（方法 {ml.get('method')}，小句 p50={ml.get('clause_p50')} p95={ml.get('clause_p95')}，"
        f"样本 {ml.get('sample_size')}）"
    )
    lines.append(
        f"- `same_speaker_merge.default_gap_seconds` = "
        f"{effective_config['same_speaker_merge']['default_gap_seconds']} s "
        f"（方法 {gap.get('method')}，同人间隔 p95={gap.get('gap_p95')}，样本 {gap.get('sample_size')}）"
    )
    lines.append(
        f"- `vignette.enabled` = {effective_config['vignette']['enabled']} "
        f"（触发词命中 {vig.get('hits')} 次）"
    )
    lines.append(
        f"- `asr_noise.enabled` = {effective_config['asr_noise']['enabled']} "
        f"（英文字符比 {noise.get('english_ratio')}，阈值 {noise.get('threshold')}）\n"
    )

    # ---- 2. 输入文件摘要 ----
    lines.append("## 2. 输入文件摘要\n")
    lines.append(f"- 文件：`{sniff_log.get('filename')}`")
    lines.append(f"- 内容类型：`{sniff_log.get('detected_type')}`"
                 f" / 字节数 {sniff_log.get('bytes')} / 字符数 {sniff_log.get('chars')}")
    lines.append(f"- 原始 ASR 轮次数：{len(raw_turns)}")
    lines.append(f"- 重建后语义轮次数：{len(reconstructed_turns)}")
    lines.append(f"- 意义单元数：{len(units)}\n")

    # ---- 3. 角色分布 ----
    lines.append("## 3. 角色分布\n")
    role_counter = Counter(t.speaker_role or "unassigned" for t in reconstructed_turns)
    lines.append("| 角色 | 轮次数 |")
    lines.append("|---|---|")
    for role, n in role_counter.most_common():
        lines.append(f"| `{role}` | {n} |")
    lines.append("")

    # ---- 4. 轮次重建前后对比 ----
    lines.append("## 4. 轮次重建\n")
    lines.append(f"- 原始轮次 {len(raw_turns)} → 重建后 {len(reconstructed_turns)}")
    if len(raw_turns) > len(reconstructed_turns):
        merged_count = len(raw_turns) - len(reconstructed_turns)
        lines.append(f"- 合并/吸收 {merged_count} 条（同人连续或跨 backchannel）")
    bridged = sum(1 for t in reconstructed_turns if "bridged_by_merge" in t.flags)
    if bridged:
        lines.append(f"- 被跨越合并的 backchannel 条数：{bridged}")
    lines.append("")

    # ---- 5. 意义单元统计 ----
    lines.append("## 5. 意义单元统计\n")
    if units:
        lengths = [u.length for u in units]
        lines.append(f"- 长度分布：min={min(lengths)}  p50={int(_fmt_percentile(lengths,0.5))}  "
                     f"mean={mean(lengths):.1f}  p95={int(_fmt_percentile(lengths,0.95))}  "
                     f"max={max(lengths)}")

        boundary_counter = Counter(u.boundary_source for u in units)
        lines.append("\n### 边界来源分布")
        lines.append("| 来源 | 数量 |")
        lines.append("|---|---|")
        for src, n in boundary_counter.most_common():
            lines.append(f"| `{src}` | {n} |")

        flag_counter = Counter()
        for u in units:
            for f in u.flags:
                flag_counter[f] += 1
        if flag_counter:
            lines.append("\n### Flag 分布")
            lines.append("| Flag | 数量 |")
            lines.append("|---|---|")
            for f, n in flag_counter.most_common():
                lines.append(f"| `{f}` | {n} |")

        # 按角色分别看长度
        lines.append("\n### 按角色的意义单元数量")
        role_u = Counter(u.speaker_role or "unassigned" for u in units)
        for role, n in role_u.most_common():
            lines.append(f"- `{role}`：{n} 条")
    lines.append("")

    # ---- 5.5 命题识别（LLM 产物）----
    lines.append("## 5.5 命题识别（LLM 产物）\n")
    if proposition_trace and proposition_trace.get("stats"):
        stats = proposition_trace["stats"]
        lines.append(f"- 候选轮次数（target_roles 且非 skip）：{stats.get('eligible_turns', 0)}")
        lines.append(f"- 实际 LLM 调用数：{stats.get('total_api_calls', 0)}")
        lines.append(f"- 成功处理轮次：{stats.get('ok_turns', 0)}")
        lines.append(f"- 失败轮次：{stats.get('failed_turns', 0)}")
        lines.append(f"- 产出命题总数：{stats.get('total_propositions', 0)}")
        lat = stats.get("total_latency_ms", 0)
        lines.append(f"- 累计 LLM 调用延迟：{lat} ms（平均每次 "
                     f"{(lat / stats['total_api_calls']) if stats.get('total_api_calls') else 0:.0f} ms）")

        if propositions:
            lines.append(f"\n### 命题长度与置信度分布\n")
            conf_vals = [p.confidence for p in propositions]
            label_lens = [len(p.label) for p in propositions]
            lines.append(f"- 置信度 min={min(conf_vals):.2f}  p50={_fmt_percentile(conf_vals, 0.5):.2f}  "
                         f"max={max(conf_vals):.2f}")
            lines.append(f"- 标签字数 min={min(label_lens)}  p50={int(_fmt_percentile(label_lens, 0.5))}  "
                         f"max={max(label_lens)}")

            # Flag 统计
            flag_counter = Counter()
            for p in propositions:
                for f in p.flags:
                    flag_counter[f] += 1
            if flag_counter:
                lines.append(f"\n### 命题 flag 分布")
                lines.append("| Flag | 数量 |")
                lines.append("|---|---|")
                for f, n in flag_counter.most_common():
                    lines.append(f"| `{f}` | {n} |")

            # 前 10 条命题示例
            lines.append(f"\n### 命题样本（前 10 条）")
            lines.append("| 命题 ID | 角色 | 标签 | 置信度 | 原文摘录 |")
            lines.append("|---|---|---|---|---|")
            for p in propositions[:10]:
                excerpt = p.source_excerpt[:40] + ("…" if len(p.source_excerpt) > 40 else "")
                lines.append(f"| `{p.proposition_id[-15:]}` | `{p.speaker_role}` | "
                             f"**{p.label}** | {p.confidence:.2f} | {excerpt} |")
    else:
        lines.append("- LLM 未启用或命题识别被跳过，本节无内容。")
        lines.append("- 若需要命题识别，请提供 `--llm-config` 指向已配置厂商的 YAML。")
    lines.append("")

    # ---- 6. 需人工复核 ----
    lines.append("## 6. 建议人工复核\n")
    review_items = []
    for t in reconstructed_turns:
        if t.speaker_role in ("other_participant", "unknown"):
            preview = t.text[:60] + ("..." if len(t.text) > 60 else "")
            review_items.append(f"- 轮次 `{t.turn_id}`（`{t.speaker_raw}` → `{t.speaker_role}`）：{preview}")
    if not review_items:
        lines.append("（无）")
    else:
        lines.append(f"以下 {len(review_items)} 条轮次被归为 `other_participant` 或 `unknown`，"
                     f"建议人工确认其真实身份：")
        lines.extend(review_items[:20])
        if len(review_items) > 20:
            lines.append(f"... 另有 {len(review_items) - 20} 条略。")
    lines.append("")

    (output_dir / "audit_report.md").write_text("\n".join(lines), encoding="utf-8")
