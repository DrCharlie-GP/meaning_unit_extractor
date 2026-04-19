"""
数据模型：CanonicalTurn（正则化轮次中间表示）与 MeaningUnit（意义单元）。

所有格式专属解析器都产出 CanonicalTurn 列表，下游分析统一在此层操作，
与原始输入格式解耦。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class CanonicalTurn:
    """正则化轮次 —— 任何输入格式解析后的统一中间表示。"""

    turn_id: str                          # 确定性 ID，如 "interview01_turn_0042"
    source_file: str                      # 原始文件名（不含路径）
    source_format: str                    # 格式类型：A / B / D
    turn_index: int                       # 该文件内的原始顺序索引

    speaker_raw: str                      # 原文标签（姓名 / 角色名 / 编号）
    speaker_role: str                     # 规范角色：interviewer / primary_informant /
                                          # family_member / other_participant / unknown
    speaker_stable_id: str                # 同一文件内跨轮次稳定的人员 ID（通常等于 speaker_raw）

    timestamp_raw: Optional[str] = None   # 原时间戳字符串，如 "00:05:33" 或 "00:02"
    timestamp_seconds: Optional[int] = None

    text: str = ""                        # 轮次正文（已做标点规范化，未做进一步编辑）
    annotations: list[dict] = field(default_factory=list)
    # 每个 annotation: {"type": "editorial", "content": "...", "char_offset": N}

    flags: list[str] = field(default_factory=list)
    # 可选标签: asr_noise_suspect / vignette_reading / backchannel /
    #           short_response / needs_manual_review

    merged_from_asr_turns: list[str] = field(default_factory=list)
    # 若该条是多条 ASR 轮次合并后的语义轮次，记录原始 turn_id 列表

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MeaningUnit:
    """意义单元 —— 最终输出的最小分析单元。"""

    unit_id: str                          # 如 "interview01_u_0123"
    source_file: str
    turn_id: str                          # 所属 CanonicalTurn 的 turn_id
    unit_index_in_turn: int               # 该单元在所属轮次中的序号（从 0 起）

    speaker_raw: str
    speaker_role: str
    speaker_stable_id: str

    timestamp_seconds: Optional[int] = None

    text: str = ""                        # 意义单元正文
    char_start_in_turn: int = 0
    char_end_in_turn: int = 0
    length: int = 0

    boundary_source: str = ""             # 该单元由哪条规则产出边界
    # 可能值: strong_term / weak_term_length / turn_end / vignette_block / backchannel_bridge

    preceding_context: str = ""           # 前一单元（同一 speaker_role 内）的文本，用于审计
    following_context: str = ""

    annotations: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Proposition:
    """
    命题 —— 由 LLM 从语义轮次中识别的分析单元，最终编码分析的主产出。

    与 MeaningUnit（子句）的区别：
      - MeaningUnit 是规则层机械切分产出，以标点为边界，保留原文句法
      - Proposition 是 LLM 解释层产出，以语义命题为边界，经过凝练
      - 每个 Proposition 带原文字符区间，可回溯到具体 MeaningUnit
    """

    proposition_id: str
    source_file: str
    turn_id: str                          # 所属 CanonicalTurn 的 turn_id
    index_in_turn: int                    # 命题在所属轮次中的序号

    speaker_raw: str
    speaker_role: str
    speaker_stable_id: str
    timestamp_seconds: Optional[int] = None

    label: str = ""                       # 4-10 字中文短标签，类似人工开放编码
    paraphrase: str = ""                  # LLM 用自己的话凝练的完整句

    source_excerpt: str = ""              # 从原文精确摘录
    source_char_start: Optional[int] = None   # 在 CanonicalTurn.text 中起始偏移
    source_char_end: Optional[int] = None     # 在 CanonicalTurn.text 中结束偏移
    related_clause_ids: list[str] = field(default_factory=list)   # 对应的 MeaningUnit.unit_id

    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)
    # 可能 flag: low_confidence / char_range_unreliable / llm_failed

    llm_provider: str = ""
    llm_model: str = ""

    # v0.2.2 新增：支持叙事民族志的分层编码。
    # 非 narrative 模式下这三个字段保持为空字符串。
    layer: str = ""      # observation / quote / interpretation / theory
    subject: str = ""    # 命题关于谁的情况（如"梁奶奶"、"一般"）
    voice: str = ""      # 命题由谁的口吻表述（如"护工"、"研究者"）

    def to_dict(self) -> dict:
        return asdict(self)
