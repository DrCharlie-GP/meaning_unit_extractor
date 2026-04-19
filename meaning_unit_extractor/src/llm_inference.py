"""
LLM 辅助参数推断层。

设计原则：
  - LLM 作为启发式的"增强器"而非"替代者"。启发式先给出基线结果，
    LLM 复核并给出修正建议与置信度。
  - LLM 输出必须是结构化 JSON，便于解析。prompt 明确要求。
  - LLM 置信度低于阈值或调用失败时，静默回退到启发式结果。
  - 所有调用记录写入审计日志，便于方法部分披露。

当前支持两类推断任务：
  1. refine_speaker_roles —— 基于说话人样本发言，确认/修正角色映射，
     并尝试识别 other_participant 的具体身份（患者/家属/访谈对象之外的人员）。
  2. detect_vignette_readings —— 在访谈员长轮次中识别情境朗读段落。
"""
from __future__ import annotations
import json
from typing import Optional

from .models import CanonicalTurn
from .llm_client import LLMClient, LLMError


SYSTEM_PROMPT_ROLE = """你是一位严谨的质性研究方法学助手，正在协助完成访谈转录的参数自动推断。
你的任务是根据每位说话人的样本发言，判断其在访谈中的角色。

可选角色标签（必须严格使用其中之一）：
- interviewer        访谈员/研究者，主要提问方
- primary_informant  主要受访者（临床医生、护士、照顾者等研究主体）
- family_member      家属，受访者身边的另一位参与者
- patient            患者本人（在照顾者访谈中偶有出现）
- other_participant  其他参与者，身份不明确
- unknown            无法判断

严格遵守：
1. 输出必须为且仅为 JSON 对象，不要任何解释性文字或 markdown 代码块。
2. 每位说话人给出 role 与 confidence（0-1 浮点数）。
3. confidence < 0.7 时请保守选择 other_participant 或 unknown。
4. 不要虚构姓名等原始样本中未出现的信息。
"""

USER_PROMPT_ROLE_TEMPLATE = """以下是一份访谈转录中每位说话人的前 {n_samples} 条代表性发言（按时间顺序）。
请判断每位说话人的角色。

{speaker_sections}

请按下列 JSON schema 返回：
{{
  "speakers": {{
    "<speaker_raw>": {{
      "role": "<one_of_allowed_roles>",
      "confidence": <float>,
      "reasoning": "<一句话简述>"
    }},
    ...
  }}
}}
"""


def _format_speaker_sections(
    samples: dict[str, list[str]],
    n_samples: int,
) -> str:
    parts = []
    for spk, texts in samples.items():
        preview = texts[:n_samples]
        block = f"[说话人: {spk}]\n"
        for i, t in enumerate(preview, 1):
            # 单条截断到 80 字，避免 prompt 过长
            show = t if len(t) <= 80 else t[:77] + "..."
            block += f"  {i}. {show}\n"
        parts.append(block)
    return "\n".join(parts)


def _collect_samples(
    turns: list[CanonicalTurn],
    per_speaker: int = 5,
    min_chars: int = 3,
) -> dict[str, list[str]]:
    """
    为每位说话人抽样发言。min_chars 定在 3 —— 过滤掉单字应答但保留短问句，
    保证即使是简短访谈也能有样本送入 LLM。
    """
    by_speaker: dict[str, list[str]] = {}
    for t in turns:
        if len(t.text) < min_chars:
            continue
        by_speaker.setdefault(t.speaker_raw, []).append(t.text)

    # 每人按出现顺序取前 per_speaker 条
    return {k: v[:per_speaker] for k, v in by_speaker.items()}


def refine_speaker_roles_with_llm(
    turns: list[CanonicalTurn],
    heuristic_result: dict,
    llm_client: LLMClient,
    confidence_threshold: float = 0.7,
) -> tuple[dict, dict]:
    """
    用 LLM 复核启发式的角色映射结果。

    返回 (final_role_map, llm_trace)。
    llm_trace 包含：调用状态、原始响应、按说话人的置信度、采纳的最终来源。
    """
    samples = _collect_samples(turns)
    if not samples:
        return heuristic_result["detected"]["speaker_role_map"], {
            "status": "skipped_no_samples",
        }

    sections = _format_speaker_sections(samples, n_samples=5)
    user_prompt = USER_PROMPT_ROLE_TEMPLATE.format(
        n_samples=5, speaker_sections=sections,
    )

    heuristic_map = heuristic_result["detected"]["speaker_role_map"]

    try:
        resp = llm_client.chat(system=SYSTEM_PROMPT_ROLE, user=user_prompt)
    except LLMError as e:
        return heuristic_map, {
            "status": "llm_call_failed",
            "error": str(e),
            "fallback": "heuristic",
        }

    if resp.mode == "disabled":
        return heuristic_map, {"status": "llm_disabled", "fallback": "heuristic"}

    # 解析 JSON
    try:
        parsed = LLMClient.parse_json_response(resp.text)
    except (json.JSONDecodeError, LLMError) as e:
        return heuristic_map, {
            "status": "json_parse_failed",
            "error": str(e),
            "raw_response": resp.text[:500],
            "fallback": "heuristic",
        }

    llm_speakers = parsed.get("speakers", {})

    # 融合：逐说话人取 LLM 结果（若置信度 >= 阈值），否则保留启发式
    final_map = {}
    per_speaker_decision = []
    for spk, heuristic_role in heuristic_map.items():
        if spk == "未知":
            final_map[spk] = "unknown"
            per_speaker_decision.append({
                "speaker_raw": spk,
                "heuristic": "unknown",
                "llm": None,
                "adopted": "unknown",
                "source": "literal_match",
            })
            continue

        llm_entry = llm_speakers.get(spk, {})
        llm_role = llm_entry.get("role")
        llm_conf = llm_entry.get("confidence", 0.0)
        llm_reasoning = llm_entry.get("reasoning", "")

        if llm_role and llm_conf >= confidence_threshold:
            adopted = llm_role
            source = "llm"
        else:
            adopted = heuristic_role
            source = "heuristic"

        final_map[spk] = adopted
        per_speaker_decision.append({
            "speaker_raw": spk,
            "heuristic": heuristic_role,
            "llm": {"role": llm_role, "confidence": llm_conf, "reasoning": llm_reasoning}
                   if llm_role else None,
            "adopted": adopted,
            "source": source,
        })

    # 处理仅 LLM 识别出但启发式未出现的说话人（一般不会发生，兜底）
    for spk, entry in llm_speakers.items():
        if spk not in final_map:
            final_map[spk] = entry.get("role", "unknown")
            per_speaker_decision.append({
                "speaker_raw": spk,
                "heuristic": None,
                "llm": entry,
                "adopted": entry.get("role", "unknown"),
                "source": "llm_only",
            })

    return final_map, {
        "status": "ok",
        "mode": resp.mode,
        "provider": resp.provider,
        "model": resp.model,
        "latency_ms": resp.latency_ms,
        "confidence_threshold": confidence_threshold,
        "per_speaker_decision": per_speaker_decision,
    }


# 默认 mock 响应 —— 用于离线测试
def default_mock_handler(system: str, user: str, provider_cfg: dict) -> str:
    """
    默认 mock：提取 user prompt 中出现的 speaker_raw，随便分配一个合理的角色。
    仅供单元测试使用，不承载真实推断能力。
    """
    import re as _re
    speakers = _re.findall(r"\[说话人:\s*(.+?)\]", user)
    if not speakers:
        return json.dumps({"speakers": {}})

    result = {}
    # 简化规则：第一个 → interviewer，其余 → primary_informant / other_participant / patient
    role_pool = ["interviewer", "primary_informant", "family_member", "other_participant"]
    for i, spk in enumerate(speakers):
        if spk == "未知":
            result[spk] = {"role": "unknown", "confidence": 1.0, "reasoning": "literal match"}
            continue
        role = role_pool[i] if i < len(role_pool) else "other_participant"
        result[spk] = {
            "role": role,
            "confidence": 0.85,
            "reasoning": f"mock assignment based on order index {i}",
        }
    return json.dumps({"speakers": result}, ensure_ascii=False)
