"""Time-series history logger for the simulation/control loop.

Writes one row per simulation step into a 52-column CSV (40-column legacy
schema v1.0 + 12 physics process columns added in v1.1). The class is plain
Python (stdlib only): no Tk dialogs, no scipy, no sklearn. Errors are written
through ``utils.logging.get_logger(__name__)``.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
from typing import Any

from utils.logging import get_logger
from utils.paths import HISTORY_DIR, ensure_dir

_logger = get_logger(__name__)

_DEFAULT_FILE_PATH = HISTORY_DIR / "history_log.csv"


class HistoryLogger:
    """实时运行状态快照记录器：本地边缘侧沉淀 52 维多维特征数据集。

    schema 演进
    -----------
    v1.0 ：原 40 列。
    v1.1 ：在 v1.0 末尾追加 12 列物理过程量；前 40 列与 v1.0 完全一致。
            读取 v1.1 数据时，老 v1.0 的 CSV 会被自动备份为 ``<原名>.v10.bak``。
    """

    def __init__(self, file_path: str | None = None) -> None:
        if file_path is None:
            ensure_dir(HISTORY_DIR)
            self.file_path: str = str(_DEFAULT_FILE_PATH)
        else:
            self.file_path = str(file_path)
        # 注意：headers 与 row 必须字段数量完全一致；
        # 任何特征扩展须同步更新下游训练脚本与 schema 校验。
        self.headers: list[str] = [
            "schema_version",
            "timestamp", "building_name", "scenario_name", "run_type", "sim_time_min",
            "hour", "electricity_price", "c_sch", "c_occ", "is_night", "r_zones_json",
            "t_out", "t_in", "load_kw", "delivered_kw", "cooling_satisfaction",
            "current_mode_before", "mode", "ai_requested_mode", "strategy_type",
            "opt_power_kw", "traditional_power_kw", "saving_rate",
            "step_kwh", "step_cost_yuan",
            "chiller_units", "chiller_plr_percent", "chiller_cop", "chiller_power_kw",
            "vrf_power_kw", "pump_power_kw", "chilled_water_flow_m3h",
            "pump_head_kpa", "pump_freq_hz", "transformer_load_percent",
            "alarms", "safety_override", "lcc_kwh_saved", "lcc_cost_saved",
            # ── v1.1 新增：物理过程量 ──
            "solar_irradiance_wm2",
            "worst_loop_dp_kpa",
            "vav_opening_avg_pct",
            "vav_openings_json",
            "exv_opening_pct",
            "duct_static_pressure_pa",
            "fan_freq_hz",
            "total_air_flow_m3h",
            "disturbance_load_kw",
            "evap_temp_c",
            "refrigerant_mass_flow_kgh",
            "chw_supply_temp_c",
        ]

        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(self.headers)
            except Exception:
                _logger.exception("HistoryLogger: failed to create %s", self.file_path)
        else:
            # 文件已存在 → 检查首行列数；若小于当前 headers 长度，
            # 视为旧 schema (v1.0)，将旧文件改名备份，再写入新表头。
            try:
                with open(self.file_path, encoding="utf-8-sig") as f:
                    first = f.readline()
                old_cols = first.count(",") + 1 if first else 0
                if 0 < old_cols < len(self.headers):
                    backup_path = self.file_path + ".v10.bak"
                    try:
                        if os.path.exists(backup_path):
                            os.remove(backup_path)
                    except Exception:
                        _logger.exception("HistoryLogger: failed to remove %s", backup_path)
                    try:
                        os.rename(self.file_path, backup_path)
                    except Exception:
                        _logger.exception(
                            "HistoryLogger: failed to rename %s -> %s",
                            self.file_path, backup_path,
                        )
                    with open(self.file_path, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.writer(f)
                        writer.writerow(self.headers)
            except Exception:
                _logger.exception("HistoryLogger: header migration failed")

    def log_step(
        self,
        building_name: str,
        scenario_name: str,
        res: dict,
        factor: dict | None = None,
        engine: Any = None,
        run_type: str = "single_step",
    ) -> None:
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sys_cfg = res.get("sys_safety_cfg", {})
            trans_limit = sys_cfg.get("transformer_capacity_kva", 2500) * sys_cfg.get("power_factor", 0.9)
            opt_p = res.get("opt_p", 0.0)
            trans_load = round((opt_p / trans_limit) * 100, 1) if trans_limit > 0 else 0.0

            hour = int((res.get("time", 0) / 60) % 24)
            electricity_price = engine.lcc.get_price_by_hour(hour) if engine else 0.0

            c_sch = factor.get("c_sch", 1.0) if factor else 1.0
            c_occ = factor.get("c_occ", 1.0) if factor else 1.0
            is_night = factor.get("is_night", False) if factor else False
            r_zones_json = json.dumps(factor.get("r_zones", {}), ensure_ascii=False) if factor else "{}"

            current_mode_before = res.get("mode_before", "")

            dt = res.get("dt", 15)
            step_kwh = round(opt_p * dt / 60.0, 2)
            step_cost_yuan = round(step_kwh * electricity_price, 2)

            hyd = res.get("hydraulic", {})
            chiller_status = res.get("chiller_status", {})

            physics = res.get("physics_state") or {}
            if not isinstance(physics, dict):
                physics = {}
            vav_dict = physics.get("vav_openings_pct") or {}
            if isinstance(vav_dict, dict) and vav_dict:
                try:
                    vav_avg_pct: Any = round(sum(float(v) for v in vav_dict.values()) / len(vav_dict), 2)
                except Exception:
                    vav_avg_pct = ""
                try:
                    vav_openings_json = json.dumps(vav_dict, ensure_ascii=False)
                except Exception:
                    vav_openings_json = "{}"
            else:
                vav_avg_pct = ""
                vav_openings_json = "{}"

            row = [
                "1.1",
                ts,
                building_name,
                scenario_name,
                run_type,
                res.get("time", 0),
                hour,
                electricity_price,
                c_sch,
                c_occ,
                is_night,
                r_zones_json,
                res.get("t_out", 0),
                res.get("t_in", 0),
                res.get("load", 0),
                res.get("delivered", 0),
                res.get("cooling_satisfaction_val", 0),
                current_mode_before,
                res.get("combo", ""),
                res.get("ai_requested_mode", ""),
                res.get("ai_suggested_type", ""),
                opt_p,
                res.get("trad_p", 0),
                res.get("rate", 0),
                step_kwh,
                step_cost_yuan,
                chiller_status.get("running_units", 0),
                chiller_status.get("plr_percent", 0),
                chiller_status.get("cop", 0),
                res.get("cmd", {}).get("Chiller_Actual_Power_kW", 0),
                res.get("cmd", {}).get("VRF_Actual_Power_kW", 0),
                hyd.get("pump_power_kw", 0),
                hyd.get("total_flow_m3h", 0),
                hyd.get("pump_head_kpa", 0),
                hyd.get("pump_freq_hz", 0),
                trans_load,
                " | ".join(res.get("cmd", {}).get("alarms", [])),
                res.get("safety_override", False),
                res.get("total_kwh_saved", 0),
                res.get("total_cost_saved", 0),
                physics.get("solar_irradiance_wm2", ""),
                physics.get("worst_loop_dp_kpa", ""),
                vav_avg_pct,
                vav_openings_json,
                physics.get("exv_opening_pct", ""),
                physics.get("duct_static_pressure_pa", ""),
                physics.get("fan_freq_hz", ""),
                physics.get("total_air_flow_m3h", ""),
                physics.get("disturbance_load_kw", ""),
                physics.get("evap_temp_c", ""),
                physics.get("refrigerant_mass_flow_kgh", ""),
                physics.get("chw_supply_temp_c", ""),
            ]
            with open(self.file_path, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception:
            _logger.exception("HistoryLogger.log_step failed")


__all__ = ["HistoryLogger"]
