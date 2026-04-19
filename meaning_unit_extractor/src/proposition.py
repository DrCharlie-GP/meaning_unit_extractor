"""
命题识别层 —— 由 LLM 从 CanonicalTurn 中识别分析命题。

与前面所有模块不同，本模块必须调用 LLM 才有价值；无 LLM 时跳过（输出空命题集）。

设计要点：
  - 粒度：以单个 CanonicalTurn 为单位调用，保证命题的上下文完整性
  - 可追溯：LLM 必须返回 source_excerpt + char_start/end；脚本独立验证
  - 回退：失败或空返回时保留子句产物，命题集为空，审计报告记录原因
  - 成本可控：只处理 target_roles 中的角色，跳过 skip_flags 标注的轮次、
    跳过短于 min_turn_length 的轮次

三种 prompt 模式：
  - interview  (默认)：适用于 A/B/D 访谈格式。不加前后文。
  - monologue  (Format E)：适用于纯自述/日记，不加前后文。
  - narrative  (Format F)：适用于叙事民族志。产出含 layer/subject/voice 三个
    额外字段；v0.2.3 起，在 prompt 中附带前后一段作为上下文参考，但命题识别
    严格限定在当前段落。
"""
from __future__ import annotations
import json
import time
from typing import Optional

from .models import CanonicalTurn, MeaningUnit, Proposition
from .llm_client import LLMClient, LLMError


# ============================================================================
# System prompts
# ============================================================================

SYSTEM_PROMPT = """你是质性研究数据分析助手，专长于从中文半结构化访谈中识别"意义单元"——可独立赋码的分析命题。

意义单元的定义（基于 Graneheim 与 Lundman 2004 的内容分析框架）：
- 承载独立的语义价值：一个观点、一个事实、一段经历、一种情感、一项诉求
- 可用简短标签概括，例如"生活习惯被迫改变"、"就医决策受费用制约"、"家庭医生角色模糊"
- 独立于原文的具体措辞也能被理解
- 不包含口头填充词、自我修正、冗余表达

不应被识别为意义单元：
- 应答词（"对"、"嗯"、"好的"、"明白"）
- 过渡话语（"然后就是"、"还有一个就是"、"反正"）
- 礼貌性客套
- 重复同一命题的多次表达（只取一次，合并字符区间）

严格遵守以下规则：
1. 输出必须是且仅是一个 JSON 对象，不要任何说明性文字，不要 markdown 代码块包裹。
2. 每个命题必须提供其在原文中的精确字符区间（start, end，0-based，end 不含）。
3. source_excerpt 必须是 text[start:end] 的精确结果，不要做任何改写、去口语化。
4. label 为 4 到 10 个中文字符的短语，类似人工开放编码结果。
5. paraphrase 用你自己的话一句话说明这个命题。
6. confidence 反映你对该命题识别的信心（0.0–1.0）。
7. 若整段文本完全不含实质命题（纯应答、纯过渡、纯寒暄），返回 {"propositions": []}。
"""


SYSTEM_PROMPT_NARRATIVE = """你是质性研究的专家助手，擅长对民族志、田野笔记、学术散文式文本做分层开放编码。

用户会给你一段来自研究者撰写的叙事文本。这类文本内含多重声音：
- 研究者本人的观察记录（如"梁奶奶眼圈红红"）
- 被研究对象的直接或间接引语（如"梁奶奶说:'你是我舅家的娃'"）
- 研究者对个案的推论与解释（如"她内心充满惶恐"）
- 对一般理论或方法学的讨论（如关于宠物疗法的论述）

为帮助你理解场景与人物，用户会同时提供"前一段上下文"与"后一段上下文"。
关键：上下文仅供你理解当前段落的语境（谁在对谁说话、什么时空、哪个人物），
命题识别严格限定在【当前段落】之内——source_excerpt 必须是当前段落的精确
子串，char_start/end 是在当前段落内的偏移。任何命题如果仅出现在上下文中，
不要识别。

你的任务是从【当前段落】识别独立可赋码的分析命题（propositions）。
粒度要求：接近 in vivo / descriptive coding 层级——贴近原文、保留描述性细节、
宁细勿粗，不要做过早的范畴化合并。300 字左右的当前段落通常产出 5-15 条命题。

每条命题必须包含以下字段：

1. label：4-10 字中文短标签
2. paraphrase：一句话凝练说明（不要用"研究者观察到""文本显示"等引言式开头）
3. source_excerpt：当前段落的精确摘录（必须是当前段落的子串，不能来自上下文）
4. source_char_start：摘录在【当前段落】内的字符起始偏移
5. source_char_end：摘录在【当前段落】内的字符结束偏移
6. subject：命题关于谁的情况
7. voice：命题由谁的口吻表述（谁说/报告/观察的）
8. layer：必须取以下四值之一
   - "observation": 研究者对具体个案的观察记录
   - "quote": 他人言语的转述（包括引号内直接引语与间接转述）
   - "interpretation": 研究者对个案的推论、心理归因、解释
   - "theory": 脱离具体个案的一般性理论或方法学讨论
9. confidence：0-1 之间的识别置信度
10. flags：数组，若 source_excerpt 无法精确摘录则加 "char_range_unreliable"

{subjects_instruction}

关键规则：
- source_excerpt 必须是【当前段落】的精确子串，不要改写或省略标点；
  若文本中存在嵌套引语（如研究者转述护工的话），voice 应追溯到最原始的
  发声者（护工），而非外层叙述者（研究者）。
- 同一段原文若同时含引语和研究者解释，应拆为不同 layer 的独立命题
- paraphrase 必须是命题式主动陈述，不要以"研究者…""文本…"开头

严格按以下 JSON 格式返回（不要加 markdown 代码块）：
{
  "propositions": [
    {
      "label": "...",
      "paraphrase": "...",
      "source_excerpt": "...",
      "source_char_start": 0,
      "source_char_end": 0,
      "subject": "...",
      "voice": "...",
      "layer": "observation",
      "confidence": 0.9,
      "flags": []
    }
  ]
}
"""


# ============================================================================
# User prompt templates
# ============================================================================

USER_PROMPT_TEMPLATE = """以下是一份访谈转录中某一位受访者的一段发言。请从中识别意义单元（命题）。

发言人角色：{speaker_role}
原文（已编号字符位置以便你定位）：
\"\"\"
{text}
\"\"\"

请按以下 JSON schema 返回：
{{
  "propositions": [
    {{
      "label": "<4-10字中文短语>",
      "paraphrase": "<用你自己的话一句说明这个命题>",
      "source_excerpt": "<精确摘自原文的字符串，不做改写>",
      "source_char_start": <int>,
      "source_char_end": <int>,
      "confidence": <0-1 浮点数>
    }}
  ]
}}
"""


USER_PROMPT_TEMPLATE_NARRATIVE = """你将看到一段来自叙事民族志文本的【当前段落】。你的任务是仅从【当前段落】识别分析命题。

为帮助你理解语境，下面同时提供前一段与后一段作为上下文参考。

{prev_block}【当前段落】（从此处识别命题；source_excerpt 与字符偏移仅在此段内有效）：
\"\"\"
{text}
\"\"\"

{next_block}再次强调：
- 只从【当前段落】识别命题，前后段上下文仅用于帮助你理解人物关系、对话场景、时空背景
- source_excerpt 必须是【当前段落】的精确子串
- source_char_start/end 是【当前段落】内的字符偏移（0-based，end 不含），与上下文段无关
"""


# ============================================================================
# Helpers
# ============================================================================

# 前后段上下文截断长度。经验值：过长会稀释当前段的注意力且浪费 token；
# 过短会丢失对话场景。200 字基本能容纳一个自然段的核心语义。
NARRATIVE_CONTEXT_MAX_CHARS = 240


def _build_subjects_instruction(allowlist: Optional[list[str]]) -> str:
    """根据是否提供主体白名单生成 prompt 中的约束段落。"""
    if allowlist:
        names = ", ".join(allowlist)
        return (
            f"subject 和 voice 字段必须从以下白名单中选择："
            f"[{names}]。若某条命题的主体或声音无法归入白名单任一项，"
            f"使用 '其他' 作为取值。"
        )
    else:
        return (
            "subject 和 voice 字段自由抽取，"
            "尽量使用文本中明确出现的人物称谓（如'梁奶奶'、'护工'、'研究者'）。"
            "若无法判定具体人物，subject 可写 '一般'，voice 可写 '研究者'。"
        )


def _truncate_context(text: str, position: str,
                      max_chars: int = NARRATIVE_CONTEXT_MAX_CHARS) -> str:
    """
    对上下文段落做截断。保留"靠近当前段"的部分。
      position="prev": 取尾部（最接近当前段）
      position="next": 取头部（最接近当前段）
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    if position == "prev":
        return "……" + text[-max_chars:]
    else:  # "next"
        return text[:max_chars] + "……"


def _build_narrative_context_blocks(
    prev_turn: Optional[CanonicalTurn],
    next_turn: Optional[CanonicalTurn],
) -> tuple[str, str]:
    """
    生成前后段上下文区块字符串。若对应段不存在，给出降级提示。
    返回 (prev_block, next_block)，两者各自以 \n\n 结尾，方便直接拼接。
    """
    if prev_turn is not None and prev_turn.text and prev_turn.text.strip():
        prev_text = _truncate_context(prev_turn.text, "prev")
        prev_block = (
            f'【前一段上下文】（仅供理解语境，不要从此处识别命题）：\n'
            f'"""\n{prev_text}\n"""\n\n'
        )
    else:
        prev_block = '【前一段上下文】：（本段为文首，无前文）\n\n'

    if next_turn is not None and next_turn.text and next_turn.text.strip():
        next_text = _truncate_context(next_turn.text, "next")
        next_block = (
            f'【后一段上下文】（仅供理解语境，不要从此处识别命题）：\n'
            f'"""\n{next_text}\n"""\n\n'
        )
    else:
        next_block = '【后一段上下文】：（本段为文末，无后文）\n\n'

    return prev_block, next_block


def _build_user_prompt(
    turn: CanonicalTurn,
    prompt_mode: str = "interview",
    prev_turn: Optional[CanonicalTurn] = None,
    next_turn: Optional[CanonicalTurn] = None,
) -> str:
    """根据 prompt_mode 构造 user prompt。"""
    if prompt_mode == "narrative":
        prev_block, next_block = _build_narrative_context_blocks(prev_turn, next_turn)
        return USER_PROMPT_TEMPLATE_NARRATIVE.format(
            prev_block=prev_block,
            next_block=next_block,
            text=turn.text,
        )
    else:
        # interview / monologue 共用原有模板
        return USER_PROMPT_TEMPLATE.format(
            speaker_role=turn.speaker_role,
            text=turn.text,
        )


def _verify_char_range(turn_text: str, start: Optional[int], end: Optional[int],
                      excerpt: str) -> tuple[Optional[int], Optional[int], bool]:
    """
    验证 LLM 返回的字符区间是否准确。

    返回 (corrected_start, corrected_end, ok)。
      ok=True：原区间有效或已成功修正
      ok=False：excerpt 在 turn_text 中找不到，区间置为 None
    """
    if not excerpt:
        return start, end, False

    # 一、先检查 LLM 给出的区间是否精确
    if start is not None and end is not None and 0 <= start < end <= len(turn_text):
        if turn_text[start:end] == excerpt:
            return start, end, True

    # 二、区间不精确，尝试在原文中搜索 excerpt
    idx = turn_text.find(excerpt)
    if idx >= 0:
        return idx, idx + len(excerpt), True

    # 三、精确搜索失败，尝试宽松匹配（去标点空白后）
    import re
    normalized_text = re.sub(r"\s+", "", turn_text)
    normalized_excerpt = re.sub(r"\s+", "", excerpt)
    if normalized_excerpt and normalized_excerpt in normalized_text:
        # 找到宽松匹配，但无法给出精确字符区间
        return None, None, True  # 区间置 None 但命题本身有效

    return None, None, False


def _find_related_clauses(
    units: list[MeaningUnit],
    turn_id: str,
    char_start: Optional[int],
    char_end: Optional[int],
) -> list[str]:
    """找出位于 [char_start, char_end) 区间内的子句 ID。"""
    if char_start is None or char_end is None:
        return []
    related = []
    for u in units:
        if u.turn_id != turn_id:
            continue
        # 子句与命题区间有重叠即归属
        if u.char_end_in_turn > char_start and u.char_start_in_turn < char_end:
            related.append(u.unit_id)
    return related


# ============================================================================
# 核心：单轮次命题识别
# ============================================================================

def extract_propositions_from_turn(
    turn: CanonicalTurn,
    units_of_turn: list[MeaningUnit],
    llm_client: LLMClient,
    confidence_threshold: float = 0.5,
    verify_range: bool = True,
    prompt_mode: str = "interview",
    subjects_allowlist: Optional[list[str]] = None,
    prev_turn: Optional[CanonicalTurn] = None,
    next_turn: Optional[CanonicalTurn] = None,
) -> tuple[list[Proposition], dict]:
    """
    对单个 turn 调用 LLM，返回命题列表与调用元数据。

    v0.2.3 新增 prev_turn/next_turn：仅在 prompt_mode="narrative" 下生效，
    作为 LLM 理解当前段语境的参考上下文；命题识别范围仍严格限定在当前 turn。
    interview / monologue 模式下 prev_turn/next_turn 被忽略，行为与 v0.2.2 相同。
    """
    file_stem = turn.source_file.rsplit(".", 1)[0]
    trace = {
        "turn_id": turn.turn_id,
        "status": "",
        "raw_response": None,
        "prompt_mode": prompt_mode,
        "has_prev_context": (prompt_mode == "narrative" and prev_turn is not None),
        "has_next_context": (prompt_mode == "narrative" and next_turn is not None),
    }

    # 选择 system prompt
    if prompt_mode == "narrative":
        subjects_instr = _build_subjects_instruction(subjects_allowlist)
        system_prompt = SYSTEM_PROMPT_NARRATIVE.replace(
            "{subjects_instruction}", subjects_instr
        )
    else:
        system_prompt = SYSTEM_PROMPT

    # 构造 user prompt
    user_prompt = _build_user_prompt(
        turn,
        prompt_mode=prompt_mode,
        prev_turn=prev_turn,
        next_turn=next_turn,
    )

    try:
        resp = llm_client.chat(
            system=system_prompt,
            user=user_prompt,
        )
    except LLMError as e:
        trace["status"] = "llm_call_failed"
        trace["error"] = str(e)
        return [], trace

    trace["llm_mode"] = resp.mode
    trace["llm_provider"] = resp.provider
    trace["llm_model"] = resp.model
    trace["latency_ms"] = resp.latency_ms

    if resp.mode == "disabled" or not resp.text.strip():
        trace["status"] = "empty_response"
        return [], trace

    try:
        parsed = LLMClient.parse_json_response(resp.text)
    except (json.JSONDecodeError, LLMError) as e:
        trace["status"] = "json_parse_failed"
        trace["error"] = str(e)
        trace["raw_response"] = resp.text[:500]
        return [], trace

    raw_props = parsed.get("propositions", [])
    if not isinstance(raw_props, list):
        trace["status"] = "invalid_schema"
        trace["raw_response"] = resp.text[:500]
        return [], trace

    propositions = []
    for i, rp in enumerate(raw_props):
        if not isinstance(rp, dict):
            continue

        label = str(rp.get("label", "")).strip()
        paraphrase = str(rp.get("paraphrase", "")).strip()
        excerpt = str(rp.get("source_excerpt", "")).strip()
        conf = float(rp.get("confidence", 0.0))
        raw_start = rp.get("source_char_start")
        raw_end = rp.get("source_char_end")

        # v0.2.2：叙事三字段
        layer = str(rp.get("layer", "")).strip()
        subject = str(rp.get("subject", "")).strip()
        voice = str(rp.get("voice", "")).strip()

        if not label and not paraphrase:
            continue

        # 合并 LLM 自声明的 flags 与脚本判定的 flags
        flags = []
        llm_flags = rp.get("flags", [])
        if isinstance(llm_flags, list):
            for f in llm_flags:
                if isinstance(f, str) and f.strip():
                    flags.append(f.strip())

        # 字符区间验证
        if verify_range:
            corrected_start, corrected_end, ok = _verify_char_range(
                turn.text, raw_start, raw_end, excerpt,
            )
            if not ok or corrected_start is None:
                if "char_range_unreliable" not in flags:
                    flags.append("char_range_unreliable")
            char_start, char_end = corrected_start, corrected_end
        else:
            char_start, char_end = raw_start, raw_end

        if conf < confidence_threshold and "low_confidence" not in flags:
            flags.append("low_confidence")

        related = _find_related_clauses(units_of_turn, turn.turn_id, char_start, char_end)

        prop_id = f"{file_stem}_p_{turn.turn_index:04d}_{i:02d}"
        propositions.append(Proposition(
            proposition_id=prop_id,
            source_file=turn.source_file,
            turn_id=turn.turn_id,
            index_in_turn=i,
            speaker_raw=turn.speaker_raw,
            speaker_role=turn.speaker_role,
            speaker_stable_id=turn.speaker_stable_id,
            timestamp_seconds=turn.timestamp_seconds,
            label=label,
            paraphrase=paraphrase,
            source_excerpt=excerpt,
            source_char_start=char_start,
            source_char_end=char_end,
            related_clause_ids=related,
            confidence=conf,
            flags=flags,
            llm_provider=resp.provider,
            llm_model=resp.model,
            layer=layer,
            subject=subject,
            voice=voice,
        ))

    trace["status"] = "ok"
    trace["propositions_count"] = len(propositions)
    return propositions, trace


# ============================================================================
# 批量调度
# ============================================================================

def extract_propositions_all(
    turns: list[CanonicalTurn],
    units: list[MeaningUnit],
    llm_client: LLMClient,
    proposition_config: dict,
    progress_callback=None,
    prompt_mode: str = "interview",
    subjects_allowlist: Optional[list[str]] = None,
) -> tuple[list[Proposition], dict]:
    """
    对所有符合条件的轮次批量做命题识别。
    返回 (all_propositions, aggregate_trace)。

    progress_callback：可选回调，签名 (current, total, message)。
    每处理一个 eligible 轮次前调用一次，完成时再调用一次（current == total）。

    v0.2.3：在 prompt_mode="narrative" 时，为每个轮次查找其 turn_index 紧邻
    的前后一段（在原始 turns 序列中查找，而非 eligible_turns），作为 prompt
    上下文参考。这样即使某个相邻段未被处理（被过滤），仍能提供叙事连贯性。
    """
    target_roles = set(proposition_config.get("target_roles", []))
    skip_flags = set(proposition_config.get("skip_flags", []))
    min_len = proposition_config.get("min_turn_length", 20)
    conf_thr = proposition_config.get("confidence_threshold", 0.5)
    verify_range = proposition_config.get("verify_char_range", True)

    # 按 turn_id 索引子句，便于命题回溯
    units_by_turn: dict[str, list[MeaningUnit]] = {}
    for u in units:
        units_by_turn.setdefault(u.turn_id, []).append(u)

    # v0.2.3：按 (source_file, turn_index) 索引所有原始 turn，用于查找前后段
    # 注意用原始 turns（非 eligible），这样被过滤的短段也能作为上下文参考
    turns_by_key: dict[tuple[str, int], CanonicalTurn] = {}
    for t in turns:
        turns_by_key[(t.source_file, t.turn_index)] = t

    # 先一次性筛选 eligible 轮次，这样 total 已知，进度条能算百分比与 ETA
    eligible_turns: list[CanonicalTurn] = []
    skipped = 0
    for turn in turns:
        if turn.speaker_role not in target_roles:
            skipped += 1
            continue
        if any(f in skip_flags for f in turn.flags):
            skipped += 1
            continue
        if len(turn.text) < min_len:
            skipped += 1
            continue
        eligible_turns.append(turn)

    all_props: list[Proposition] = []
    per_turn_traces = []
    stats = {
        "total_turns": len(turns),
        "eligible_turns": len(eligible_turns),
        "processed_turns": 0,
        "skipped_turns": skipped,
        "ok_turns": 0,
        "failed_turns": 0,
        "total_propositions": 0,
        "total_latency_ms": 0,
        "total_api_calls": 0,
        "prompt_mode": prompt_mode,
        "context_enabled": (prompt_mode == "narrative"),
    }

    total = len(eligible_turns)
    for i, turn in enumerate(eligible_turns):
        if progress_callback:
            short_id = turn.turn_id.split("_")[-1] if "_" in turn.turn_id else turn.turn_id
            progress_callback(i, total, f"处理 {short_id}")

        # v0.2.3：仅 narrative 模式查找前后段
        prev_t: Optional[CanonicalTurn] = None
        next_t: Optional[CanonicalTurn] = None
        if prompt_mode == "narrative":
            prev_t = turns_by_key.get((turn.source_file, turn.turn_index - 1))
            next_t = turns_by_key.get((turn.source_file, turn.turn_index + 1))

        props, trace = extract_propositions_from_turn(
            turn,
            units_by_turn.get(turn.turn_id, []),
            llm_client,
            confidence_threshold=conf_thr,
            verify_range=verify_range,
            prompt_mode=prompt_mode,
            subjects_allowlist=subjects_allowlist,
            prev_turn=prev_t,
            next_turn=next_t,
        )
        per_turn_traces.append(trace)
        stats["total_api_calls"] += 1
        if trace.get("latency_ms"):
            stats["total_latency_ms"] += trace["latency_ms"]

        if trace["status"] == "ok":
            stats["ok_turns"] += 1
            stats["processed_turns"] += 1
            all_props.extend(props)
            stats["total_propositions"] += len(props)
        else:
            stats["failed_turns"] += 1

    # 终态信号
    if progress_callback:
        progress_callback(total, total, "完成")

    trace_summary = {
        "stats": stats,
        "per_turn_traces": per_turn_traces[:50],
        "per_turn_traces_truncated": len(per_turn_traces) > 50,
    }
    return all_props, trace_summary


# ============================================================================
# Mock handler（离线测试用）
# ============================================================================

def default_proposition_mock_handler(system: str, user: str, provider_cfg: dict) -> str:
    """
    Mock handler：从"当前段落"中"识别"一两条命题用于测试。

    v0.2.3：narrative 模式下，user prompt 含多个 \"\"\" 块（prev / current / next），
    需要提取【当前段落】那一块。通过识别 '【当前段落】' 标记来定位。
    """
    import re as _re

    # 识别 prompt 模式
    is_narrative = ("叙事民族志" in system) or ("【当前段落】" in user)

    if is_narrative:
        # narrative 模式：以块标签"【当前段落】（从此处识别命题"为锚点，
        # 定位其后的第一个三引号块；此锚点在 prompt 顶部说明文字里不会出现。
        m = _re.search(
            r'【当前段落】（从此处识别命题[^"]*?"""\n(.+?)\n"""',
            user, flags=_re.DOTALL,
        )
    else:
        # interview / monologue：抓取第一个三引号块
        m = _re.search(r'"""\n(.+?)\n"""', user, flags=_re.DOTALL)

    if not m:
        return json.dumps({"propositions": []})
    text = m.group(1)
    if len(text) < 20:
        return json.dumps({"propositions": []})

    props = []
    # 第 1 条：前 30 字
    first_excerpt = text[:min(30, len(text))]
    p1 = {
        "label": "Mock命题一",
        "paraphrase": "这是由 mock handler 生成的第一个测试命题",
        "source_excerpt": first_excerpt,
        "source_char_start": 0,
        "source_char_end": len(first_excerpt),
        "confidence": 0.85,
    }
    if is_narrative:
        p1.update({
            "layer": "observation",
            "subject": "梁奶奶",
            "voice": "研究者",
            "flags": [],
        })
    props.append(p1)

    # 第 2 条：中段 30 字（若原文够长）
    if len(text) > 80:
        mid_start = len(text) // 2
        mid_excerpt = text[mid_start:mid_start + 30]
        p2 = {
            "label": "Mock命题二",
            "paraphrase": "这是由 mock handler 生成的第二个测试命题",
            "source_excerpt": mid_excerpt,
            "source_char_start": mid_start,
            "source_char_end": mid_start + len(mid_excerpt),
            "confidence": 0.75,
        }
        if is_narrative:
            p2.update({
                "layer": "interpretation",
                "subject": "研究者",
                "voice": "研究者",
                "flags": [],
            })
        props.append(p2)

    return json.dumps({"propositions": props}, ensure_ascii=False)
