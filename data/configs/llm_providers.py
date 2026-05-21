"""Reporting-only LLM provider presets.

The legacy ``PROVIDER_PRESETS`` dict served two roles: it backed the UI
provider combo *and* fed the cloud-LLM control strategy. After FEAT-003 the
control-loop LLM path is deleted, so this module exposes the same shape of
data **strictly for the reporting / Copilot path**:

* ``ReportingService.explain_alarm`` may call an LLM to produce a natural
  language explanation;
* ``ReportAgent.enrich_with_summary`` may prepend an LLM summary to a
  text report.

Every entry is tagged ``role='reporting'`` so accidental consumers cannot
mistake them for control providers. A static test
(``tests/test_no_llm_in_control_v2.py``) enforces that no module under
``core/control``, ``core/simulation``, ``core/safety``, ``core/optimizer``
or ``prediction/`` imports anything containing the substring ``llm``.
"""

from __future__ import annotations

LLM_PROVIDER_PRESETS_FOR_REPORTING: dict = {
    "qwen": {
        "display_name": "千问 / 阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
        "role": "reporting",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "role": "reporting",
    },
    "doubao": {
        "display_name": "豆包 / 火山方舟",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-1-6",
        "api_key_env": "ARK_API_KEY",
        "role": "reporting",
    },
    "hunyuan": {
        "display_name": "腾讯混元 / 元宝预留",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "model": "hunyuan-standard",
        "api_key_env": "HUNYUAN_API_KEY",
        "role": "reporting",
    },
    "custom": {
        "display_name": "自定义OpenAI兼容接口",
        "base_url": "",
        "model": "",
        "api_key_env": "",
        "role": "reporting",
    },
}

__all__ = ["LLM_PROVIDER_PRESETS_FOR_REPORTING"]
