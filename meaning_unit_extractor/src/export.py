"""
输出层：将 CanonicalTurn、MeaningUnit（子句）、Proposition（命题）导出为可交付文件。

每次运行的输出目录结构：
    <output_dir>/
        propositions.csv            主产出：LLM 识别的命题表，供编码分析
        propositions.jsonl          同上，程序友好
        clauses.csv                 规则层子句表（原 meaning_units.csv）
        clauses.jsonl
        canonical_turns.jsonl       轮次中间表示
        audit_report.md
        config_snapshot.yaml
        metadata.json
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
from datetime import datetime

import yaml

from .models import CanonicalTurn, MeaningUnit, Proposition


CLAUSE_FIELDS = [
    "unit_id",
    "source_file",
    "turn_id",
    "unit_index_in_turn",
    "speaker_raw",
    "speaker_role",
    "speaker_stable_id",
    "timestamp_seconds",
    "text",
    "length",
    "char_start_in_turn",
    "char_end_in_turn",
    "boundary_source",
    "preceding_context",
    "following_context",
    "flags",
    "annotations",
]

PROPOSITION_FIELDS = [
    "proposition_id",
    "source_file",
    "turn_id",
    "index_in_turn",
    "speaker_raw",
    "speaker_role",
    "speaker_stable_id",
    "timestamp_seconds",
    "label",
    "paraphrase",
    "source_excerpt",
    "source_char_start",
    "source_char_end",
    "related_clause_ids",
    "confidence",
    "flags",
    "llm_provider",
    "llm_model",
    # v0.2.2 新增：叙事民族志的分层编码字段
    "layer",
    "subject",
    "voice",
]


def export_meaning_units(
    units: list[MeaningUnit],
    output_dir: Path,
) -> None:
    """导出子句表为 clauses.csv/jsonl。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "clauses.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CLAUSE_FIELDS)
        writer.writeheader()
        for u in units:
            row = u.to_dict()
            row["flags"] = json.dumps(row["flags"], ensure_ascii=False)
            row["annotations"] = json.dumps(row["annotations"], ensure_ascii=False)
            writer.writerow({k: row.get(k, "") for k in CLAUSE_FIELDS})

    jsonl_path = output_dir / "clauses.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for u in units:
            fh.write(json.dumps(u.to_dict(), ensure_ascii=False) + "\n")


def export_propositions(
    propositions: list[Proposition],
    output_dir: Path,
) -> None:
    """导出命题表为 propositions.csv/jsonl。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "propositions.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PROPOSITION_FIELDS)
        writer.writeheader()
        for p in propositions:
            row = p.to_dict()
            row["flags"] = json.dumps(row["flags"], ensure_ascii=False)
            row["related_clause_ids"] = json.dumps(row["related_clause_ids"], ensure_ascii=False)
            writer.writerow({k: row.get(k, "") for k in PROPOSITION_FIELDS})

    jsonl_path = output_dir / "propositions.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for p in propositions:
            fh.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")


def export_canonical_turns(
    turns: list[CanonicalTurn],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "canonical_turns.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for t in turns:
            fh.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")


def export_config_snapshot(
    snapshot: dict,
    output_dir: Path,
) -> None:
    path = output_dir / "config_snapshot.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(snapshot, fh, allow_unicode=True, sort_keys=False)


def export_metadata(
    input_path: Path,
    sniff_log: dict,
    format_detection,
    effective_config: dict,
    output_dir: Path,
    llm_trace: dict | None = None,
    proposition_trace: dict | None = None,
) -> None:
    meta = {
        "tool": effective_config.get("meta", {}),
        "run_timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "input": {
            "path": str(input_path),
            "sha256": _sha256_of_file(input_path),
            **sniff_log,
        },
        "format_detection": {
            "format_code": format_detection.format_code,
            "first_match_line": format_detection.first_match_line,
            "hit_counts": format_detection.hit_counts,
        },
        "llm_inference": llm_trace or {"status": "not_invoked"},
        "proposition": proposition_trace or {"status": "not_invoked"},
    }
    with open(output_dir / "metadata.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
