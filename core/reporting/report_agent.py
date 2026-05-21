"""Reporting-only post-step composer (renamed from legacy ``AIReportAgent``).

This agent **never** decides control modes. It only composes a multi-section
text report from a result dict produced by
:class:`services.simulation_service.SimulationService` (or, equivalently,
:meth:`core.simulation.engine.WhiteBoxEngine.execute_step`).

Behavioural changes vs. the legacy 3312-3426 banner:

* The legacy branches that displayed the deprecated cloud / fake-BiLSTM
  strategy class names for ``ai_suggested_type`` are gone (those classes
  have been deleted by FEAT-003). The remaining branches handle
  ``MPCStrategy`` and ``RuleBasedStrategy`` explicitly; any other type
  string falls through to a generic display.
* The agent NO LONGER decides modes; it only composes text.
* The agent optionally accepts an :class:`~core.reporting.llm_client.LLMClient`
  and exposes :meth:`enrich_with_summary`. When the client is missing or
  not configured, :meth:`enrich_with_summary` returns the original
  ``report_text`` unchanged so the base report path always works without
  any LLM dependency.
"""

from __future__ import annotations

import json
from typing import Any

from data.configs.defaults import DISPLAY_NAME_MAP, MODE_LABELS
from utils.logging import get_logger

from .llm_client import LLMClient

_logger = get_logger(__name__)


class ReportAgent:
    """Read-only formatter for engine result dicts.

    Parameters
    ----------
    llm_client : LLMClient or None, optional
        When provided **and** ``llm_client.is_configured()`` returns True,
        :meth:`enrich_with_summary` will prepend a natural-language
        summary to a report. Otherwise the original text is returned
        verbatim. The base report path (:meth:`generate_report`) never
        touches the LLM.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    # --------------------------------------------------------- key renaming
    @staticmethod
    def _cn_key(key: str) -> str:
        if key in DISPLAY_NAME_MAP:
            return DISPLAY_NAME_MAP[key]
        if key.startswith("BACnet_BO_") and "Valve" in key:
            return f"楼宇自控_阀门开启指令_{key.split('_')[-1]}"
        if key.startswith("BACnet_BI_") and "Valve" in key and key.endswith("_FB"):
            return f"楼宇自控_阀门状态反馈_{key.split('_')[-2]}"
        return key

    # ---------------------------------------------------------- main report
    def generate_report(
        self,
        res: dict[str, Any],
        s_name: str,
        is_single_step: bool = True,
    ) -> str:
        """Compose a multi-section text report from an engine result dict.

        The shape of ``res`` matches the dict returned by
        :meth:`WhiteBoxEngine.execute_step` (and therefore
        :meth:`SimulationService.run_single_step`). Missing top-level
        keys fall through to placeholders so the formatter never raises.
        """
        cmd = res.get("cmd", {}) or {}
        alarms = cmd.get("alarms") or []
        shed = cmd.get("shedding_seq") or []
        alarms_str = "\n    * ".join(alarms) if alarms else "状态监测正常，系统无告警"
        shed_str = "\n   ".join(shed) if shed else "变压器容量正常，未触发减载"

        bacnet_cmd_cn = {
            self._cn_key(k): v for k, v in cmd.items() if k.startswith("BACnet_")
        }
        struct_outputs_cn = {
            self._cn_key(k): v for k, v in cmd.items()
            if "Actual_" in k or "Delivered_" in k
        }

        ai_type = res.get("ai_suggested_type", "")
        if ai_type == "MPCStrategy":
            strat_type = "本地多步预测控制(MPC)"
        elif ai_type == "RuleBasedStrategy":
            strat_type = "本地阈值规则控制"
        else:
            # CloudAI / BiLSTM branches are deleted; anything else displays
            # generically. The legacy strings are not referenced anywhere.
            strat_type = ai_type if ai_type else "本地规则"

        ai_info_node = res.get("ai_info", {}) or {}
        if ai_info_node.get("fallback", False):
            ai_reason = "策略层失败，已切回安全降级路径"
        else:
            ai_reason = ai_info_node.get("reason", "本地白箱规则执行")

        ai_req = MODE_LABELS.get(
            res.get("ai_requested_mode", "LOW"),
            res.get("ai_requested_mode", "LOW"),
        )
        ai_risk = ai_info_node.get("risk_note", "-")
        # ``is_revised`` answers "did the safety supervisor modify the
        # rule layer's recommendation?". The pre-safety proposal is
        # surfaced as ``res['proposed_mode']`` (concern #11). For
        # backward compatibility, when ``proposed_mode`` is absent we
        # fall back to comparing the (post-safety) ``ai_requested_mode``
        # against the engine's final mode.
        proposed = res.get("proposed_mode")
        if proposed is None or proposed == "-":
            proposed = res.get("ai_requested_mode")
        is_revised = "是" if proposed != res.get("combo") else "否"

        s_cfg = res.get("sys_safety_cfg", {}) or {}
        trans_limit = (
            s_cfg.get("transformer_capacity_kva", 0)
            * s_cfg.get("power_factor", 1)
        )
        trans_load = (
            round((res.get("opt_p", 0) / trans_limit) * 100, 1)
            if trans_limit > 0 else 0.0
        )

        rep = (
            f"【工程运行与能效审计报告】 测试工况：{s_name} | 控制策略：{strat_type}\n"
            f"{'='*50}\n"
            f"[1] 热力环境与安全防线\n"
            f"  ▶ 建筑瞬态需求冷负荷: {res.get('load', 0)} kW\n"
            f"  ▶ 实际交付供冷量: {res.get('delivered', 0)} kW\n"
            f"  ▶ 供冷品质评定: {res.get('cooling_satisfaction_disp', '-')}\n"
            f"  ▶ 模拟室内温度: {res.get('t_in', 0)} ℃ "
            f"(室外等效温度 {res.get('t_out', 0)} ℃)\n"
            f"  ▶ 变压器减载保护: {shed_str}\n\n"
            f"[2] 策略发令与 BACnet 执行镜像 (综合 COP={res.get('active_cop', 0)})\n"
            f"  ▶ 策略推荐模式: {ai_req}\n"
            f"  ▶ 推荐理由: {ai_reason}\n"
            f"  ▶ 潜在风险提示: {ai_risk}\n"
            f"  ▶ 安全层是否修正指令: {is_revised}\n"
            f"  ▶ 最终执行模式: "
            f"[{MODE_LABELS.get(res.get('combo', '-'), res.get('combo', '-'))}] "
            f"- {res.get('mech', '-')}\n"
            f"  ▶ 设备实测功率:\n"
            f"{json.dumps(struct_outputs_cn, ensure_ascii=False, indent=2)}\n"
            f"  ▶ BACnet 寄存器映射:\n"
            f"{json.dumps(bacnet_cmd_cn, ensure_ascii=False, indent=2)}\n\n"
            f"[3] DDC 安全审计\n"
            f"  ▶ 安全预警记录: {alarms_str}\n"
        )

        c_stat = res.get("chiller_status", {}) or {}
        if c_stat.get("running_units", 0) > 0:
            rep += (
                f"  ▶ 冷水机组运行: 投运 {c_stat['running_units']} 台 | "
                f"PLR {c_stat.get('plr_percent', 0)}% | COP {c_stat.get('cop', 0)}\n"
            )

        rep += (
            f"  ▶ 功耗对照: 传统基准 {res.get('trad_p', 0)} kW vs "
            f"优化控制 {res.get('opt_p', 0)} kW (节能率 "
            f"{res.get('rate_disp', '0.0%')})\n"
            f"  ▶ 主变压器负载率: {trans_load}%\n"
            f"  ▶ 底层安全参数: 防喘振下限 "
            f"{s_cfg.get('central_min_plr', 0)*100}% | "
            f"变压器容量 {trans_limit} kW | "
            f"室温上限 {s_cfg.get('indoor_temp_limit', 0)} ℃\n"
        )

        hyd = res.get("hydraulic", {}) or {}
        if hyd.get("is_sleep", True):
            hyd_str = "  ▶ 冷冻水系统: VRF 独立运转，中央水系统休眠。\n"
        else:
            branches = hyd.get("branches", []) or []
            active = [b for b in branches if b.get("flow_m3h", 0) > 0]
            max_br = (
                max(active, key=lambda b: b.get("branch_total_dp_kpa", 0))
                if active else None
            )
            max_vel = (
                max(active, key=lambda b: b.get("velocity_ms", 0))
                if active else None
            )
            warn_list = [
                f"{b['zone_name']}({b['warning']})"
                for b in branches if b.get("warning")
            ]
            warnings_str = "、".join(warn_list) if warn_list else "各支路流速正常"
            hyd_str = (
                f"  ▶ 供回水温度/温差: {hyd.get('supply_temp_c', 0)} ℃ / "
                f"{hyd.get('return_temp_c', 0)} ℃ (ΔT={hyd.get('delta_t_c', 0)} ℃)\n"
                f"  ▶ 水泵运行: {hyd.get('pump_freq_hz', 0)} Hz "
                f"({hyd.get('pump_speed_rpm', 0)} rpm) | 变频开度 "
                f"{hyd.get('pump_vfd_percent', 0)}%\n"
                f"  ▶ 系统总流量: {hyd.get('total_flow_m3h', 0)} m³/h | "
                f"水泵功率: {hyd.get('pump_power_kw', 0)} kW | "
                f"扬程: {hyd.get('pump_head_kpa', 0)} kPa / "
                f"{hyd.get('pump_head_m', 0.0)} m\n"
                f"  ▶ 最不利支路: "
                f"{max_br['zone_name'] if max_br else '-'} (阻力 "
                f"{max_br['branch_total_dp_kpa'] if max_br else 0} kPa)\n"
                f"  ▶ 最高流速支路: "
                f"{max_vel['zone_name'] if max_vel else '-'} (流速 "
                f"{max_vel['velocity_ms'] if max_vel else 0} m/s)\n"
                f"  ▶ 流速超限告警: {warnings_str}\n"
            )
        rep += f"\n[4] 冷冻水流程数字孪生数据\n{hyd_str}"

        lcc = res.get("lcc_info")
        if lcc:
            rep += (
                f"\n[5] LCC 全生命周期经济性估算\n"
                f"  ▶ 计价模式: "
                f"{'分时电价(TOU)' if lcc.get('use_tou') else '平段固定电价'}\n"
                f"  ▶ 仿真时段累计节电量: "
                f"{res.get('total_kwh_saved', 0.0):.2f} kWh\n"
                f"  ▶ 15年全期财务净现值(NPV): {lcc.get('NPV', 0)} 万元\n"
                f"  【说明】本估算基于典型日+季节系数推算，非完整 8760 小时审计，"
                f"仅供参考。"
            )
        return rep

    # --------------------------------------------------- LLM-side enrichment
    def enrich_with_summary(self, report_text: str) -> str:
        """Optionally prepend an LLM-generated summary to a base report.

        Returns ``report_text`` unchanged when no LLM client is configured
        or when the LLM call fails. The base report content is preserved
        verbatim either way.
        """
        client = self.llm_client
        if client is None:
            return report_text
        try:
            if not client.is_configured():
                return report_text
            summary = client.summarize({"report_excerpt": report_text[:1500]})
            if not summary or not str(summary).strip():
                return report_text
            return f"【AI 运维摘要】\n{str(summary).strip()}\n\n{report_text}"
        except Exception:
            _logger.exception("ReportAgent.enrich_with_summary failed; returning original text")
            return report_text


__all__ = ["ReportAgent"]
