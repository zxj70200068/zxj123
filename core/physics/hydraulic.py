"""Chilled-water hydraulic network digital twin."""

from __future__ import annotations

import math
from typing import Any


class HydraulicNetworkModel:
    def __init__(self, zone_specs: dict, sys_config: dict) -> None:
        self.zone_specs = zone_specs
        self.sys_config = sys_config
        self.dn_sizes: dict[str, float] = {
            "DN200": 0.20, "DN150": 0.15, "DN125": 0.125,
            "DN100": 0.10, "DN80": 0.08, "DN65": 0.065, "DN50": 0.05,
        }
        total_design = sum(spec.get("design_load_kw", 1000.0) for spec in self.zone_specs.values())
        self.design_flow_m3h: float = max(1.0, total_design / (1.163 * 5.0))

    def calculate(
        self,
        cooling_distribution: dict,
        supply_temp_c: float = 7.0,
        return_temp_c: float = 12.0,
    ) -> dict[str, Any]:
        delta_t_c = max(1.0, return_temp_c - supply_temp_c)
        total_flow_m3h = 0.0
        branches_data: list[dict] = []
        branch_dps: list[float] = []
        is_active = any(v > 0 for v in cooling_distribution.values())

        for zone_name, cooling_kw in cooling_distribution.items():
            z_cfg = self.zone_specs.get(zone_name, {})
            dn = z_cfg.get("pipe_dn", "DN100")
            diameter_m = self.dn_sizes.get(dn, 0.10)
            length_m = float(z_cfg.get("pipe_length_m", 100.0))
            design_kw = float(z_cfg.get("design_load_kw", 1000.0))
            term_type = z_cfg.get("terminal_type", "末端设备")
            term_dp_ref = float(z_cfg.get("terminal_dp_kpa", 35.0))

            if cooling_kw > 0 and is_active:
                flow_m3h = cooling_kw / (1.163 * delta_t_c)
                total_flow_m3h += flow_m3h
                flow_m3s = flow_m3h / 3600.0
                area = math.pi * (diameter_m ** 2) / 4.0
                velocity_ms = flow_m3s / area if area > 0 else 0.0

                friction_loss_kpa = length_m * 0.08 * (velocity_ms ** 2)
                local_loss_kpa = 5.0 * (velocity_ms ** 2)
                terminal_dp_kpa = term_dp_ref
                branch_total_dp_kpa = friction_loss_kpa + local_loss_kpa + terminal_dp_kpa
                branch_dps.append(branch_total_dp_kpa)

                valve_opening = (
                    min(100.0, max(15.0, (cooling_kw / design_kw) * 100.0))
                    if design_kw > 0 else 15.0
                )
                air_flow_m3h = cooling_kw * 250.0
                if velocity_ms < 0.5:
                    warning = "低流速区，换热可能衰减"
                elif velocity_ms > 2.5:
                    warning = "高流速区，阻力和噪声偏大"
                else:
                    warning = ""
            else:
                flow_m3h = velocity_ms = friction_loss_kpa = local_loss_kpa = 0.0
                terminal_dp_kpa = branch_total_dp_kpa = air_flow_m3h = 0.0
                valve_opening = 0.0 if not is_active else 15.0
                warning = ""

            branches_data.append({
                "zone_name": zone_name,
                "cooling_kw": round(cooling_kw, 1),
                "flow_m3h": round(flow_m3h, 2),
                "dn": dn,
                "velocity_ms": round(velocity_ms, 2),
                "friction_loss_kpa": round(friction_loss_kpa, 2),
                "local_loss_kpa": round(local_loss_kpa, 2),
                "terminal_dp_kpa": round(terminal_dp_kpa, 2),
                "valve_opening": round(valve_opening, 1),
                "branch_total_dp_kpa": round(branch_total_dp_kpa, 2),
                "warning": warning,
                "terminal_type": term_type,
                "air_flow_m3h": round(air_flow_m3h, 0),
                "supply_air_temp": 14.0 if cooling_kw > 0 else "--",
                "return_air_temp": 26.0 if cooling_kw > 0 else "--",
            })

        empty_checkpoints = {
            "chiller_out": {"T": supply_temp_c, "P": 0.0, "F": 0.0},
            "pump_out": {"T": supply_temp_c, "P": 0.0, "F": 0.0},
            "distributor": {"T": supply_temp_c, "P": 0.0, "F": 0.0},
            "term_in": {"T": supply_temp_c, "P": 0.0, "F": "--"},
            "term_out": {"T": return_temp_c, "P": 0.0, "F": "--"},
            "return_main": {"T": return_temp_c, "P": 0.0, "F": 0.0},
        }

        if is_active and branch_dps:
            RESERVED_PRESSURE_KPA = 20.0  # 分水器至最不利末端资用压差预留值
            pump_head_kpa = max(branch_dps) + RESERVED_PRESSURE_KPA
            pump_head_m = pump_head_kpa / 9.81
            pump_efficiency = 0.72
            pump_power_kw = (
                (total_flow_m3h * pump_head_m / (367.0 * pump_efficiency))
                if pump_head_m > 0 else 0.0
            )
            pump_freq_hz = 30.0 + min(20.0, (total_flow_m3h / self.design_flow_m3h) * 20.0)
            pump_speed_rpm = int((pump_freq_hz / 50.0) * 1450.0)
            pump_vfd_percent = round((pump_freq_hz / 50.0) * 100.0, 1)

            p_return = 200.0
            p_pump_suction = p_return - 50.0
            p_pump_out = p_pump_suction + pump_head_kpa
            p_distributor = p_pump_out - 10.0

            active_branches = [b for b in branches_data if b["flow_m3h"] > 0]
            if active_branches:
                max_friction = max(b["friction_loss_kpa"] for b in active_branches)
                max_term_dp = max(b["terminal_dp_kpa"] for b in active_branches)
            else:
                max_friction = 0.0
                max_term_dp = 0.0
            p_term_in = p_distributor - max_friction
            p_term_out = p_term_in - max_term_dp

            checkpoints = {
                "chiller_out": {"T": supply_temp_c, "P": round(p_pump_suction, 1), "F": round(total_flow_m3h, 2)},
                "pump_out": {"T": supply_temp_c, "P": round(p_pump_out, 1), "F": round(total_flow_m3h, 2)},
                "distributor": {"T": supply_temp_c, "P": round(p_distributor, 1), "F": round(total_flow_m3h, 2)},
                "term_in": {"T": supply_temp_c, "P": round(p_term_in, 1), "F": "--"},
                "term_out": {"T": return_temp_c, "P": round(p_term_out, 1), "F": "--"},
                "return_main": {"T": return_temp_c, "P": round(p_return, 1), "F": round(total_flow_m3h, 2)},
            }
        else:
            pump_head_kpa = pump_head_m = pump_power_kw = pump_freq_hz = 0.0
            pump_speed_rpm = 0
            pump_vfd_percent = 0.0
            checkpoints = empty_checkpoints

        # 并联支路水力平衡检查：识别压差跨度过大的失调风险
        if is_active and len(branch_dps) > 1:
            active_dps = [b for b in branch_dps if b > 0]
            if len(active_dps) > 1:
                dp_spread = max(active_dps) - min(active_dps)
                if dp_spread > 15.0:
                    branches_data.append({
                        "zone_name": "水力平衡",
                        "cooling_kw": 0.0, "flow_m3h": 0.0, "dn": "-",
                        "velocity_ms": 0.0, "friction_loss_kpa": 0.0,
                        "local_loss_kpa": 0.0, "terminal_dp_kpa": 0.0,
                        "valve_opening": 0.0, "branch_total_dp_kpa": round(dp_spread, 2),
                        "warning": f"并联支路压差跨度{dp_spread:.1f}kPa，建议核查平衡阀",
                        "terminal_type": "系统提示", "air_flow_m3h": 0,
                        "supply_air_temp": "--", "return_air_temp": "--",
                    })

        return {
            "supply_temp_c": supply_temp_c,
            "return_temp_c": return_temp_c,
            "delta_t_c": delta_t_c,
            "total_flow_m3h": round(total_flow_m3h, 2),
            "pump_head_kpa": round(pump_head_kpa, 2),
            "pump_head_m": round(pump_head_m, 2),
            "pump_power_kw": round(pump_power_kw, 2),
            "pump_freq_hz": round(pump_freq_hz, 1),
            "pump_speed_rpm": pump_speed_rpm,
            "pump_vfd_percent": pump_vfd_percent,
            "checkpoints": checkpoints,
            "branches": branches_data,
            "is_sleep": not is_active,
        }


__all__ = ["HydraulicNetworkModel"]
