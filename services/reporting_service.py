"""Reporting service: text-only summarization for runs and alarms.

This service NEVER returns a control mode. It only returns text, which is
what makes it safe to wire an LLM client into the
:meth:`explain_alarm` path: a buggy LLM cannot accidentally drive the
plant because the supervisory loop never reads from this service.

The service has two responsibilities:

* :meth:`summarize_run` -- read recent history rows from the local CSV
  log and produce a multi-section text report. Empty / missing history
  is tolerated (the boilerplate path returns >= 100 chars of text).
* :meth:`explain_alarm` -- when an LLM client is configured, ask it for a
  natural-language explanation of an alarm; otherwise return a
  deterministic boilerplate explanation.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.reporting.llm_client import LLMClient
from core.reporting.report_agent import ReportAgent
from utils.logging import get_logger
from utils.paths import HISTORY_DIR

_logger = get_logger(__name__)

_DEFAULT_HISTORY_PATH = HISTORY_DIR / "history_log.csv"


class ReportingService:
    """Text-only summarization service.

    Parameters
    ----------
    history_path : str or Path, optional
        CSV path to read recent history rows from. Defaults to
        ``utils.paths.HISTORY_DIR / 'history_log.csv'``. Missing files
        are tolerated.
    llm_client : LLMClient, optional
        When supplied **and** ``llm_client.is_configured()`` is True,
        :meth:`explain_alarm` calls :meth:`LLMClient.summarize` to
        produce a natural-language explanation. Otherwise the method
        returns a deterministic boilerplate string.
    """

    DEFAULT_RECENT_ROWS: int = 50

    def __init__(
        self,
        history_path: Path | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.history_path: Path = (
            Path(history_path) if history_path is not None else _DEFAULT_HISTORY_PATH
        )
        self.llm_client = llm_client
        self._report_agent = ReportAgent(llm_client=llm_client)

    # --------------------------------------------------------- helpers
    def _read_recent_rows(self, max_rows: int) -> list[dict[str, str]]:
        """Read up to ``max_rows`` most recent rows from the history CSV.

        Returns an empty list when the file is missing, empty, or any IO
        failure occurs. Never raises.
        """
        try:
            if not self.history_path.exists():
                return []
            with open(self.history_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception:
            _logger.exception(
                "ReportingService: failed to read history at %s", self.history_path,
            )
            return []
        if not rows:
            return []
        return rows[-max_rows:]

    # ----------------------------------------------------------- run summary
    def summarize_run(self, scenario_name: str) -> str:
        """Produce a multi-section text report for ``scenario_name``.

        The report is composed of several paragraphs so the empty-history
        boilerplate path is comfortably above 100 characters (the test
        contract). The format is intentionally human-readable, not JSON.
        """
        rows = self._read_recent_rows(self.DEFAULT_RECENT_ROWS)
        sections: list[str] = []

        sections.append(
            "【运行摘要报告】"
            f" 工况: {scenario_name or '(未指定)'} | "
            f"历史记录文件: {self.history_path!s}"
        )
        sections.append("=" * 60)

        if not rows:
            sections.append(
                "[1] 数据可用性\n"
                "  ▶ 当前历史日志为空或未找到。该报告以默认占位文字呈现，\n"
                "    待仿真运行结束并由 HistoryLogger 写入 history_log.csv 后\n"
                "    可重新生成包含真实功率、节能率与告警分布的完整审计内容。"
            )
            sections.append(
                "[2] 控制链状态\n"
                "  ▶ LLM 仅用于报告与告警解释；不参与控制链。\n"
                "  ▶ 当前为占位摘要，未读取到真实指令镜像。"
            )
            sections.append(
                "[3] 后续动作建议\n"
                "  ▶ 启动一次完整的时序仿真，或在 DDC/BACnet 边缘网关运行后\n"
                "    将真实点位写入历史 CSV。"
            )
            return "\n".join(sections)

        # ---- Real data path ----------------------------------------------
        n = len(rows)
        latest = rows[-1]

        def _try_float(d: dict[str, str], key: str) -> float | None:
            try:
                v = d.get(key)
                if v is None or v == "":
                    return None
                return float(v)
            except Exception:
                return None

        powers = [p for p in (_try_float(r, "opt_p") for r in rows) if p is not None]
        loads = [p for p in (_try_float(r, "load") for r in rows) if p is not None]
        rates = [p for p in (_try_float(r, "rate") for r in rows) if p is not None]
        avg_p = sum(powers) / len(powers) if powers else 0.0
        avg_l = sum(loads) / len(loads) if loads else 0.0
        avg_r = sum(rates) / len(rates) if rates else 0.0

        sections.append(
            f"[1] 数据采样\n"
            f"  ▶ 读取记录数: {n}\n"
            f"  ▶ 最新时刻: {latest.get('timestamp', '-')}\n"
            f"  ▶ 最新模式: {latest.get('combo', '-')}"
        )
        sections.append(
            f"[2] 平均能效指标\n"
            f"  ▶ 平均瞬态冷负荷: {avg_l:.1f} kW\n"
            f"  ▶ 平均优化功率: {avg_p:.1f} kW\n"
            f"  ▶ 平均节能率: {avg_r*100:.2f}%"
        )
        sections.append(
            f"[3] 告警快照\n"
            f"  ▶ 最近一行告警: {latest.get('alarms', '-')}"
        )
        sections.append(
            "[4] 备注\n"
            "  ▶ LLM 仅用于报告与告警解释，不参与控制链。"
        )
        return "\n".join(sections)

    # -------------------------------------------------------- alarm explain
    def explain_alarm(self, alarm_text: str) -> str:
        """Return a natural-language explanation of ``alarm_text``.

        When ``llm_client`` is configured, the explanation is produced by
        the LLM via :meth:`LLMClient.summarize`. Otherwise, a
        deterministic boilerplate string is returned. Either way the
        result is **text only**: this method NEVER returns a control mode.
        """
        text = (alarm_text or "").strip()
        client = self.llm_client
        if client is not None:
            try:
                if client.is_configured():
                    out = client.summarize({
                        "context": "HVAC alarm explanation",
                        "alarm": text,
                    })
                    if out and str(out).strip():
                        return str(out).strip()
            except Exception:
                _logger.exception(
                    "ReportingService.explain_alarm: LLM call failed; "
                    "falling back to boilerplate"
                )
        return (
            f"【告警解释（默认模板）】\n"
            f"原始告警: {text or '(空)'}\n"
            "可能原因: 设备越限、控制链安全层主动降级或时序锁定未到期。\n"
            "建议: 检查相关 BACnet 点位、确认水力 / 安全配置与现场时序计划是否一致。\n"
            "提示: 该说明仅用于辅助运维；最终决策仍以本地控制链与现场工程师审核为准。"
        )

    # ---------------------------------------------------- step formatter
    def format_step_result(self, res: dict[str, Any], scenario_name: str) -> str:
        """Convenience: format an engine result dict into a report.

        Wraps :meth:`ReportAgent.generate_report` so UI callers do not
        need to import ``core.reporting.*`` directly.
        """
        return self._report_agent.generate_report(res, scenario_name, is_single_step=True)


__all__ = ["ReportingService"]
