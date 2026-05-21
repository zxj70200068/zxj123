"""Reporting-only LLM client.

This client is only used by the reporting layer. Calling it from any
control loop is forbidden. The control-loop LLM path was deleted in
FEAT-003 (see ``tests/test_no_llm_in_control_v2.py``); this module lives
under ``core/reporting`` precisely because the static guard scans
``core/control``, ``core/simulation``, ``core/safety``, ``core/optimizer``
and ``prediction/`` -- not ``core/reporting``.

Functional scope (vs. the legacy ``LLMClient``):

* Method ``get_recommendation`` is GONE. The replacement, :meth:`summarize`,
  asks the model for a **natural-language summary** of the supplied state
  (no JSON, no ``recommended_mode`` field).
* The OpenAI-compatible ``response_format={"type": "json_object"}`` flag
  has been dropped. The output is plain text.
* :meth:`is_configured` and :meth:`test_connection` are retained so the
  UI's reporting LLM panel can light up the status indicator without
  changing.

Network IO is performed through :mod:`urllib.request`; no third-party HTTP
client is used. Errors are converted to :class:`ValueError` so callers
can degrade gracefully (the reporting service falls back to deterministic
boilerplate when an LLM call fails).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from utils.logging import get_logger

_logger = get_logger(__name__)


class LLMClient:
    """OpenAI-compatible LLM client used **only** by the reporting layer."""

    def __init__(self, provider: str, api_config: dict[str, Any]) -> None:
        self.provider = provider
        p_config = api_config.get("providers", {}).get(provider, {})
        self.base_url: str = p_config.get("base_url", "")
        self.model: str = p_config.get("model", "")
        self.api_key: str = p_config.get("api_key", "")
        if self.base_url and not self.base_url.endswith("/chat/completions"):
            self.endpoint: str = self.base_url.rstrip("/") + "/chat/completions"
        else:
            self.endpoint = self.base_url

    # ------------------------------------------------------------- helpers
    def is_configured(self) -> bool:
        """Return True if base_url, model and api_key are all populated."""
        return bool(self.base_url and self.model and self.api_key)

    def test_connection(self) -> tuple[bool, str]:
        """Best-effort smoke probe: send a tiny ``hi`` and check status."""
        if not self.is_configured():
            return False, "API 配置不完整：请填写 Base URL、模型名称和 API Key。"
        try:
            req = urllib.request.Request(self.endpoint, method="POST")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("Content-Type", "application/json")
            data = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            }).encode("utf-8")
            with urllib.request.urlopen(req, data=data, timeout=5) as resp:
                if resp.status == 200:
                    return True, f"API 连接测试成功：模型 [{self.model}] 响应正常。"
            return False, "API 连接失败：返回非预期状态码。"
        except Exception as exc:
            return False, f"网络连接或鉴权失败: {exc}"

    # ------------------------------------------------------------- summarize
    def summarize(self, state: dict[str, Any]) -> str:
        """Return a natural-language summary of the supplied operating state.

        Parameters
        ----------
        state : dict
            Free-form snapshot of the run. Common keys: ``time_of_day``,
            ``t_out``, ``t_in``, ``load``, ``current_mode``, ``alarms``.
            Missing keys are tolerated (the prompt only mentions what is
            present).

        Returns
        -------
        str
            Plain text summary. **Never** a JSON object or a control mode.

        Raises
        ------
        ValueError
            On configuration / network / parsing failure. Callers in the
            reporting layer catch this and fall back to deterministic
            boilerplate.
        """
        if not self.is_configured():
            raise ValueError("API 配置不完整，无法发起请求")

        state_lines: list[str] = []
        for key, val in state.items():
            try:
                state_lines.append(f"- {key}: {val}")
            except Exception:
                state_lines.append(f"- {key}: <unrenderable>")
        state_block = "\n".join(state_lines) if state_lines else "(无)"

        prompt = (
            "你是一名 HVAC 运维工程师助手。请根据下面的系统运行状态，"
            "用 3-6 句中文自然语言总结当前运行情况、能耗特征以及任何告警的可能原因。"
            "不要输出 JSON、Markdown 表格或控制模式建议；只输出运维报告语段。\n\n"
            f"系统状态：\n{state_block}\n"
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise HVAC reporting assistant. "
                        "Output a natural-language Chinese summary only. "
                        "Never output JSON or control modes."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(self.endpoint, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(
                req, data=json.dumps(payload).encode("utf-8"), timeout=10,
            ) as resp:
                return self._parse_response(resp)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"API 返回错误状态码: {exc.code}") from exc
        except Exception as exc:
            raise ValueError(f"网络请求失败: {exc}") from exc

    @staticmethod
    def _parse_response(resp: Any) -> str:
        try:
            resp_json = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"响应解析失败: {exc}") from exc
        if "choices" not in resp_json or not resp_json["choices"]:
            raise ValueError("响应格式错误：缺少 choices 字段")
        content = resp_json["choices"][0].get("message", {}).get("content", "")
        if not content or not str(content).strip():
            raise ValueError("响应内容为空")
        return str(content).strip()


__all__ = ["LLMClient"]
