"""
多厂商 LLM 客户端 —— 统一接口，支持 OpenAI 兼容协议与 Anthropic 协议。

依赖：仅 requests（避免引入 openai / anthropic SDK，降低环境负担）。
模式：
  - disabled   不调用，返回空响应
  - mock       使用预设响应，用于离线测试
  - live       真实 HTTP 调用

返回值统一为 str（模型生成的文本）。对 JSON 任务，调用方自行解析。
"""
from __future__ import annotations
import os
import json
import time
from dataclasses import dataclass
from typing import Optional, Callable


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    raw: dict                    # 厂商原始响应（便于审计）
    latency_ms: int
    mode: str                    # disabled / mock / live


class LLMClient:
    """统一 LLM 调用接口。配置来自 llm_config.yaml。"""

    def __init__(self, llm_config: dict, mock_handler: Optional[Callable] = None):
        """
        llm_config: 来自 llm_config.yaml 的完整字典
        mock_handler: 测试注入；签名 (system, user, provider_cfg) -> str
        """
        self.config = llm_config
        self.mode = llm_config.get("mode", "disabled")
        self.defaults = llm_config.get("defaults", {})
        self._mock_handler = mock_handler

        if self.mode == "live":
            self.active = llm_config.get("active_provider")
            if not self.active:
                raise LLMError("llm_config.mode=live 但未指定 active_provider")
            providers = llm_config.get("providers", {})
            if self.active not in providers:
                raise LLMError(f"active_provider='{self.active}' 未在 providers 中定义")
            self.provider_cfg = providers[self.active]
        elif self.mode in ("disabled", "mock"):
            self.active = llm_config.get("active_provider", "mock")
            self.provider_cfg = llm_config.get("providers", {}).get(self.active, {})
        else:
            raise LLMError(f"未知的 mode: {self.mode}")

    # ---------- 对外主接口 ----------
    def chat(self, system: str, user: str,
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> LLMResponse:
        """通用对话接口，返回 LLMResponse。"""
        start = time.time()

        if self.mode == "disabled":
            return LLMResponse(
                text="",
                model=self.provider_cfg.get("model", "disabled"),
                provider=self.active,
                raw={"mode": "disabled"},
                latency_ms=0,
                mode="disabled",
            )

        if self.mode == "mock":
            if self._mock_handler is None:
                raise LLMError("mode=mock 但未提供 mock_handler")
            text = self._mock_handler(system, user, self.provider_cfg)
            return LLMResponse(
                text=text,
                model=self.provider_cfg.get("model", "mock"),
                provider=self.active,
                raw={"mode": "mock", "handler_response": text},
                latency_ms=int((time.time() - start) * 1000),
                mode="mock",
            )

        # live
        ptype = self.provider_cfg.get("type", "openai_compatible")
        temp = temperature if temperature is not None else self.defaults.get("temperature", 0.0)
        mt = max_tokens if max_tokens is not None else self.defaults.get("max_tokens", 2000)
        timeout = self.defaults.get("timeout_seconds", 60)
        max_retries = self.defaults.get("max_retries", 2)
        backoff = self.defaults.get("retry_backoff_seconds", 2)

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                if ptype == "openai_compatible":
                    raw = self._call_openai_compatible(system, user, temp, mt, timeout)
                    text = raw["choices"][0]["message"]["content"]
                elif ptype == "anthropic":
                    raw = self._call_anthropic(system, user, temp, mt, timeout)
                    # Anthropic 响应: content 是 [{"type":"text","text":"..."}]
                    text = "".join(
                        blk.get("text", "")
                        for blk in raw.get("content", [])
                        if blk.get("type") == "text"
                    )
                else:
                    raise LLMError(f"不支持的 provider type: {ptype}")

                return LLMResponse(
                    text=text,
                    model=self.provider_cfg.get("model", ""),
                    provider=self.active,
                    raw=raw,
                    latency_ms=int((time.time() - start) * 1000),
                    mode="live",
                )
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise LLMError(f"LLM 调用失败（{max_retries+1} 次尝试后）: {e}") from e

    # ---------- 协议适配 ----------
    def _get_api_key(self) -> str:
        env_key = self.provider_cfg.get("api_key_env")
        if not env_key:
            return ""
        key = os.environ.get(env_key, "")
        if not key and self.active != "local":
            raise LLMError(f"环境变量 {env_key} 未设置")
        return key

    def _call_openai_compatible(self, system: str, user: str,
                                temperature: float, max_tokens: int,
                                timeout: int) -> dict:
        import requests
        url = self.provider_cfg["base_url"].rstrip("/") + "/chat/completions"
        api_key = self._get_api_key()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = {
            "model": self.provider_cfg["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _call_anthropic(self, system: str, user: str,
                        temperature: float, max_tokens: int,
                        timeout: int) -> dict:
        import requests
        url = self.provider_cfg["base_url"].rstrip("/") + "/messages"
        api_key = self._get_api_key()
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": self.provider_cfg.get("anthropic_version", "2023-06-01"),
        }
        body = {
            "model": self.provider_cfg["model"],
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    # ---------- 便捷 JSON 解析 ----------
    @staticmethod
    def parse_json_response(text: str) -> dict:
        """
        尽力从模型响应中解析 JSON。
        处理 ```json ... ``` 代码块包裹、响应含前后缀说明的情况。
        """
        if not text:
            raise LLMError("响应为空")
        s = text.strip()
        # 去除 markdown 代码块
        if s.startswith("```"):
            s = s.split("\n", 1)[1] if "\n" in s else s
            if s.endswith("```"):
                s = s[:-3]
            s = s.strip()
            # 可能还残留 "json" 标记
            if s.startswith("json"):
                s = s[4:].strip()
        # 提取首个 {...} JSON 对象
        if not s.startswith("{"):
            start = s.find("{")
            end = s.rfind("}")
            if start >= 0 and end > start:
                s = s[start:end + 1]
        return json.loads(s)
