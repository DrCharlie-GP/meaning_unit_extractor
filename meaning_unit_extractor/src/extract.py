"""
meaning_unit_extractor —— 主入口。

用法：
    python -m src.extract \\
        --input data/raw/访谈_01.txt \\
        --output-dir data/processed/访谈_01/ \\
        [--base-config base_defaults.yaml] \\
        [--llm-config llm_config.yaml] \\
        [--override "segmentation.max_length=80"] ...

单次处理一份访谈，批处理由外层 shell 循环完成。
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import yaml

from .file_reader import read_transcript
from .format_router import detect_format
from .parsers import get_parser
from .inference import run_full_inference
from .llm_client import LLMClient
from .llm_inference import refine_speaker_roles_with_llm, default_mock_handler
from .config import build_effective_config
from .reconstruction import merge_same_speaker_and_backchannel
from .segment import segment_all_turns
from .proposition import extract_propositions_all, default_proposition_mock_handler
from .progress import CliProgressBar
from .export import (
    export_meaning_units,
    export_canonical_turns,
    export_config_snapshot,
    export_metadata,
    export_propositions,
)
from .audit import generate_audit_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从单份访谈转录提取意义单元（支持 LLM 辅助参数推断）"
    )
    parser.add_argument("--input", required=True, help="输入转录文件路径")
    parser.add_argument("--output-dir", required=True, help="输出目录（将被创建）")
    parser.add_argument("--base-config", default=None,
                        help="基础配置路径；默认使用项目根的 base_defaults.yaml")
    parser.add_argument("--llm-config", default=None,
                        help="LLM 配置路径；不提供则禁用 LLM")
    parser.add_argument("--override", action="append", default=[],
                        help='CLI 参数覆盖，形如 key.path=value，可多次使用')
    parser.add_argument("--llm-mock", action="store_true",
                        help="强制使用 mock 模式（离线测试用）")
    # v0.2.2 新增：显式声明单一说话人格式，绕过自动检测
    parser.add_argument(
        "--format",
        choices=["auto", "monologue", "narrative"],
        default="auto",
        help="输入格式。auto=自动检测 A/B/C/D（默认）；"
             "monologue=纯自述/日记（Format E）；"
             "narrative=叙事民族志/田野笔记（Format F，产出含 layer/subject/voice 字段）",
    )
    parser.add_argument(
        "--speaker-label",
        default="自述者",
        help="Format E 下的说话人标签（默认'自述者'）",
    )
    parser.add_argument(
        "--narrator-label",
        default="研究者",
        help="Format F 下的叙述者标签（默认'研究者'）",
    )
    parser.add_argument(
        "--subjects",
        default=None,
        help="Format F 下的主体白名单，逗号分隔。"
             "例：--subjects \"梁奶奶,余奶奶,护工,研究者,一般\"。"
             "不提供时 LLM 自由抽取。",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误：输入文件不存在：{input_path}", file=sys.stderr)
        return 2

    # 定位 base_config
    if args.base_config:
        base_config_path = Path(args.base_config)
    else:
        base_config_path = Path(__file__).resolve().parent.parent / "base_defaults.yaml"
    if not base_config_path.exists():
        print(f"错误：base_defaults.yaml 不存在：{base_config_path}", file=sys.stderr)
        return 2

    with open(base_config_path, encoding="utf-8") as fh:
        base_config = yaml.safe_load(fh)

    # 装配 LLM 客户端
    # Mock handler 根据 system prompt 开头判断用途（角色识别 vs 命题识别），分别派发
    from .llm_inference import default_mock_handler as role_mock_handler

    def combined_mock_handler(system: str, user: str, pcfg: dict) -> str:
        if system.startswith("你是一位严谨的质性研究方法学助手"):
            return role_mock_handler(system, user, pcfg)
        # 否则认为是命题识别
        return default_proposition_mock_handler(system, user, pcfg)

    llm_client = None
    llm_config_loaded = None
    if args.llm_config:
        with open(args.llm_config, encoding="utf-8") as fh:
            llm_config_loaded = yaml.safe_load(fh)
        if args.llm_mock:
            llm_config_loaded["mode"] = "mock"
        llm_client = LLMClient(llm_config_loaded, mock_handler=combined_mock_handler)
    elif args.llm_mock:
        llm_config_loaded = {
            "active_provider": "mock",
            "mode": "mock",
            "defaults": {"temperature": 0.0, "max_tokens": 2000},
            "providers": {"mock": {"type": "openai_compatible", "model": "mock"}},
        }
        llm_client = LLMClient(llm_config_loaded, mock_handler=combined_mock_handler)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. 读文件 ----
    text, sniff_log = read_transcript(input_path)
    print(f"[read] {input_path.name} 类型={sniff_log['detected_type']} "
          f"字符={sniff_log['chars']}")

    # ---- 2. 格式检测与解析 ----
    # v0.2.2：若用户显式声明 monologue 或 narrative，跳过自动检测
    if args.format in ("monologue", "narrative"):
        from .parsers import parse_format_e, parse_format_f

        # 构造一个伪 FormatDetection 对象，让下游审计与 metadata 有统一数据可用
        class _ExplicitFormat:
            can_process = True
            diagnostic = ""
            hit_counts = {}
            first_match_line = None
            def __init__(self, code):
                self.format_code = code

        if args.format == "monologue":
            fmt = _ExplicitFormat("E_monologue")
            print(f"[format] 显式声明为 E_monologue（纯自述/日记）")
            raw_turns, header_metadata = parse_format_e(
                text, input_path.name, speaker_label=args.speaker_label,
            )
        else:  # narrative
            fmt = _ExplicitFormat("F_narrative")
            print(f"[format] 显式声明为 F_narrative（叙事民族志）")
            raw_turns, header_metadata = parse_format_f(
                text, input_path.name, narrator_label=args.narrator_label,
            )
        print(f"[parse] 解析得 {len(raw_turns)} 条原始轮次")
    else:
        fmt = detect_format(text)
        print(f"[format] 检测为 {fmt.format_code}")

        if not fmt.can_process:
            # v0.2.2：给出显式声明 monologue/narrative 的建议
            hint = (
                "\n提示：如果这份文件是纯自述/日记（单一说话人、无标签），"
                "请加参数 --format monologue；"
                "如果是叙事民族志/田野笔记（研究者撰写的学术散文），"
                "请加参数 --format narrative。"
            )
            print(f"[abort] 无法自动处理：{fmt.diagnostic}{hint}", file=sys.stderr)
            output_dir.mkdir(parents=True, exist_ok=True)
            diag_path = output_dir / "diagnostic.md"
            diag_path.write_text(
                f"# 无法处理\n\n格式检测：`{fmt.format_code}`\n\n{fmt.diagnostic}\n{hint}\n",
                encoding="utf-8",
            )
            return 3

        # ---- 3. 解析 ----
        parse_fn = get_parser(fmt.format_code)
        raw_turns, header_metadata = parse_fn(text, input_path.name)
        print(f"[parse] 解析得 {len(raw_turns)} 条原始轮次")

    # ---- 4. 启发式推断 ----
    inference_result = run_full_inference(raw_turns, fmt.format_code, base_config)
    detected_config_from_heuristic = inference_result["detected"]

    # ---- 5. LLM 辅助推断 ----
    llm_trace = None
    llm_assist_mode = base_config.get("inference", {}).get("llm_assist", "auto")
    # v0.2.2：E/F 格式均为单一说话人，不需要 LLM 角色复核
    is_single_speaker_format = fmt.format_code in ("E_monologue", "F_narrative")
    if (llm_client is not None
            and llm_assist_mode != "disabled"
            and llm_client.mode != "disabled"
            and not is_single_speaker_format):
        print(f"[llm] 启动 LLM 辅助角色推断（{llm_client.mode} / {llm_client.active}）")
        conf_thr = base_config.get("inference", {}).get("llm_confidence_threshold", 0.7)
        refined_map, trace = refine_speaker_roles_with_llm(
            raw_turns, inference_result, llm_client, confidence_threshold=conf_thr,
        )
        detected_config_from_heuristic["speaker_role_map"] = refined_map
        llm_trace = trace
    elif is_single_speaker_format:
        print(f"[llm] 跳过角色复核（{fmt.format_code} 为单一说话人格式）")

    # ---- 6. 配置合并 ----
    effective_config, snapshot = build_effective_config(
        base_config,
        detected_config_from_heuristic,
        user_overrides=args.override,
    )

    # ---- 7. 把最终 role_map 应用到每个轮次 ----
    role_map = effective_config.get("speaker_role_map", {})
    for t in raw_turns:
        if not t.speaker_role or t.speaker_role in ("", "unknown"):
            # 格式 B 已预填；格式 A/D 与 "未知" 在这里填
            t.speaker_role = role_map.get(t.speaker_raw, t.speaker_role or "unknown")

    # ---- 8. 轮次重建 ----
    # v0.2.2：E/F 格式无 ASR 伪切分问题，不做同人合并
    if is_single_speaker_format:
        reconstructed_turns = list(raw_turns)
        print(f"[reconstruct] 跳过（{fmt.format_code} 无需合并），轮次数 {len(reconstructed_turns)}")
    elif effective_config.get("same_speaker_merge", {}).get("enabled", True):
        reconstructed_turns = merge_same_speaker_and_backchannel(
            raw_turns,
            gap_threshold_seconds=effective_config["same_speaker_merge"]["default_gap_seconds"],
            backchannel_enabled=effective_config["backchannel"]["enabled"]
                                and effective_config["same_speaker_merge"].get("merge_across_backchannel", True),
            backchannel_words=effective_config["backchannel"]["words"],
            backchannel_max_chars=effective_config["backchannel"]["max_chars"],
        )
        print(f"[reconstruct] 原始 {len(raw_turns)} → 重建后 {len(reconstructed_turns)}")
    else:
        reconstructed_turns = list(raw_turns)
        print(f"[reconstruct] 原始 {len(raw_turns)} → 重建后 {len(reconstructed_turns)}")

    # ---- 9. 意义单元切分 ----
    units = segment_all_turns(reconstructed_turns, base_config, effective_config)
    print(f"[segment] 产出 {len(units)} 条子句")

    # ---- 10. 命题识别（LLM 驱动，可选）----
    propositions = []
    proposition_trace = None
    prop_cfg = base_config.get("proposition", {})
    prop_enabled = prop_cfg.get("enabled", "auto")
    can_run_props = (
        llm_client is not None
        and llm_client.mode != "disabled"
        and prop_enabled in (True, "auto", "forced")
    )
    if can_run_props:
        # v0.2.2：按格式决定 prompt 模式与主体白名单
        if fmt.format_code == "F_narrative":
            prompt_mode = "narrative"
            subjects_allowlist = (
                [s.strip() for s in args.subjects.split(",") if s.strip()]
                if args.subjects else None
            )
            subjects_msg = (
                f"，主体白名单 [{', '.join(subjects_allowlist)}]"
                if subjects_allowlist else "，主体自由抽取"
            )
            print(f"[proposition] 开始命题识别（LLM {llm_client.mode} / {llm_client.active}，"
                  f"narrative 模式{subjects_msg}）")
        elif fmt.format_code == "E_monologue":
            prompt_mode = "monologue"
            subjects_allowlist = None
            print(f"[proposition] 开始命题识别（LLM {llm_client.mode} / {llm_client.active}，"
                  f"monologue 模式）")
        else:
            prompt_mode = "interview"
            subjects_allowlist = None
            print(f"[proposition] 开始命题识别（LLM {llm_client.mode} / {llm_client.active}）")

        progress_bar = CliProgressBar(label="[proposition]")
        try:
            propositions, proposition_trace = extract_propositions_all(
                reconstructed_turns, units, llm_client, prop_cfg,
                progress_callback=progress_bar.update,
                prompt_mode=prompt_mode,
                subjects_allowlist=subjects_allowlist,
            )
        finally:
            progress_bar.close()
        stats = proposition_trace["stats"]
        print(f"[proposition] 完成：处理 {stats['processed_turns']} 轮次，"
              f"产出 {len(propositions)} 条命题，"
              f"失败 {stats['failed_turns']} 轮次，"
              f"累计 {stats['total_latency_ms']/1000:.1f}s")
    else:
        print(f"[proposition] 跳过（LLM 未启用或配置要求跳过）")

    # ---- 11. 输出 ----
    export_meaning_units(units, output_dir)
    export_canonical_turns(reconstructed_turns, output_dir)
    export_propositions(propositions, output_dir)
    export_config_snapshot(snapshot, output_dir)
    export_metadata(input_path, sniff_log, fmt, effective_config,
                    output_dir, llm_trace=llm_trace,
                    proposition_trace=proposition_trace)
    generate_audit_report(
        input_path.name, sniff_log, fmt, raw_turns, reconstructed_turns,
        units, propositions, inference_result, effective_config,
        llm_trace, proposition_trace, output_dir,
    )
    print(f"[done] 输出至 {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
