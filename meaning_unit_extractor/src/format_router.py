"""
格式检测路由器。

检测四种已知格式（按优先级匹配）：
  A  timestamped_name     姓名(HH:MM:SS):          临床访谈 ASR 原始输出
  B  semantic_role        访谈者：/受访者：        人工编辑过的照顾者访谈
  D  numeric_speaker      说话人 \\d+ MM:SS         带说话人分离的 ASR 输出
  C  unlabeled            无说话人标签             仅做诊断退出

返回 FormatDetection（格式代号 + 首命中行号 + 诊断信息）。
"""
from __future__ import annotations
import re
from dataclasses import dataclass


# 四种格式的行级探针
PROBES = {
    "A_timestamped_name": re.compile(
        r"^[\u4e00-\u9fa5A-Za-z]{1,10}\(\d{1,2}:\d{2}(?::\d{2})?\)[:：]"
    ),
    "B_semantic_role": re.compile(
        r"^(访谈者|访谈员|研究者|受访者|被访者|照顾者|问|答)[:：]"
    ),
    "D_numeric_speaker": re.compile(
        r"^说话人\s+(?:\d+|未知)\s+\d{1,2}:\d{2}"
    ),
    # 格式 C 的特征是「有音频文件引用块但没有说话人标签」
    "C_audio_chunked_unlabeled": re.compile(
        r"^\[.+\.m4a\s+\d{1,2}:\d{2}\]"
    ),
}


@dataclass
class FormatDetection:
    format_code: str                 # A_timestamped_name / B_semantic_role / D_numeric_speaker /
                                     # C_audio_chunked_unlabeled / unknown
    first_match_line: int            # 首个命中探针的行号（从 1 起）
    hit_counts: dict                 # 每种格式在前 N 行中的命中数
    sample_lines: list[str]          # 前若干有效行（用于审计报告）
    can_process: bool                # C 与 unknown 不可自动处理
    diagnostic: str                  # 无法处理时给出人类可读的说明


def detect_format(text: str, scan_lines: int = 60) -> FormatDetection:
    """
    对文本前 N 行做模式匹配，返回检测结果。

    规则：
      - 任一探针命中次数 ≥ 2，且是所有探针中命中最多者 → 该格式
      - 格式 C 即使命中，也标 can_process=False
      - 无任何命中 → unknown，不可处理
    """
    lines = text.split("\n")
    # 去除首部空行，但保留原始行号
    head = lines[:scan_lines]

    hits = {name: 0 for name in PROBES}
    first_match = {name: None for name in PROBES}
    for idx, ln in enumerate(head, start=1):
        stripped = ln.strip()
        if not stripped:
            continue
        for name, pat in PROBES.items():
            if pat.match(stripped):
                hits[name] += 1
                if first_match[name] is None:
                    first_match[name] = idx

    # 选取命中最多且 >= 2 的格式
    best = max(hits.items(), key=lambda kv: kv[1])
    format_code, best_hits = best

    sample_lines = [ln for ln in head[:20] if ln.strip()][:10]

    if best_hits < 2:
        return FormatDetection(
            format_code="unknown",
            first_match_line=-1,
            hit_counts=hits,
            sample_lines=sample_lines,
            can_process=False,
            diagnostic=(
                "未检出任何已知格式的稳定标志串。"
                "已知格式有：A（姓名+HH:MM:SS 冒号）、B（访谈者/受访者 冒号）、"
                "D（说话人 N MM:SS）。"
                "请检查文件是否需要人工预编辑补齐说话人标签。"
            ),
        )

    if format_code == "C_audio_chunked_unlabeled":
        return FormatDetection(
            format_code=format_code,
            first_match_line=first_match[format_code] or -1,
            hit_counts=hits,
            sample_lines=sample_lines,
            can_process=False,
            diagnostic=(
                "检测到音频文件引用块格式（格式 C），但该格式不含说话人标签，"
                "说话人切换嵌在正文内，无法自动可靠分割。"
                "请先完成人工或 LLM 辅助的说话人预标注后再运行脚本。"
            ),
        )

    return FormatDetection(
        format_code=format_code,
        first_match_line=first_match[format_code] or -1,
        hit_counts=hits,
        sample_lines=sample_lines,
        can_process=True,
        diagnostic="",
    )
