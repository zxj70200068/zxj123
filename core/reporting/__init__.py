"""Reporting layer (text-only).

This package owns the LLM client and the post-step report formatter. It is
the **only** place under ``core/`` allowed to talk to an LLM, and it is
explicitly **not** part of the supervisory control loop. See the module
docstring of :mod:`core.reporting.llm_client` for the rationale.
"""

from core.reporting.llm_client import LLMClient
from core.reporting.report_agent import ReportAgent

__all__ = ["LLMClient", "ReportAgent"]
