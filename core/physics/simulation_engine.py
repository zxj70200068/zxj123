"""Process-oriented white-box physics simulation engine.

The class is independent of the closed-loop control simulation and can be
instantiated and exercised on its own. UI/Tk logging from the legacy code
has been replaced with :func:`utils.logging.get_logger`.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from utils.logging import get_logger

_logger = get_logger(__name__)


class PhysicsSimulationEngine:
    """过程导向白盒物理仿真引擎（独立类，不接入主循环）。

    设计目标：
        将原有"黑盒结果"型输出（仅整体能耗与 COP）扩展为"过程导向"白盒视图，
        逐环节展示水侧/风侧/多联机/外扰的中间物理量，便于答辩可视化与机理排障。

    覆盖范围：
        1. 水侧（CHW Loop）  ：基于 Q = c·m·ΔT 与水泵相似律反算流量、压降、阀位、频率、扬程。
        2. 风侧（VAV）        ：基于 Q = ρ·cp·V·ΔT 反算各区送风量与 VAV 开度。
        3. 多联机（VRF）      ：基于 R410A 气液两相焓差反算制冷剂质量流量。
        4. 环境扰动           ：太阳常数 1353 W/m² 基准 + 大气透射率 + 太阳高度角等。

    所有方法返回 dict（键名带物理量单位后缀），可直接馈入 UI/日志/报表层。
    """

    # ───────────────────── 物性与工程基准常量 ─────────────────────
    SOLAR_CONSTANT = 1353.0
    CP_WATER_KJ = 4.187
    RHO_WATER = 1000.0
    RHO_CP_AIR = 1.2
    DELTA_T_AIR_K = 10.0
    R410A_LATENT_KJ = 190.0

    # 水力网络
    RATED_COOLING_LOAD_KW = 2400.0
    RATED_LOOP_DP_KPA = 320.0
    PUMP_RATED_FREQ_HZ = 50.0
    PUMP_MIN_FREQ_HZ = 20.0
    GRAVITY = 9.81

    # 风侧
    RATED_AIR_FLOW_M3H = 60000.0
    DUCT_STATIC_MIN_PA = 100.0
    DUCT_STATIC_MAX_PA = 300.0
    FAN_RATED_FREQ_HZ = 50.0
    FAN_MIN_FREQ_HZ = 20.0

    # 多联机 EXV
    EXV_BASE_OPENING_PCT = 25.0
    EXV_GAIN_PCT = 65.0
    EXV_MIN_PCT = 10.0
    EXV_MAX_PCT = 95.0
    VRF_RATED_LOAD_KW = 360.0

    # 环境扰动
    ATMOS_TRANSMISSIVITY = 0.70
    ENVELOPE_GAIN_COEFF = 0.55
    OPAQUE_U_W_M2K = 1.20
    INDOOR_SET_TEMP_C = 26.0
    SUNRISE_HOUR = 6.0
    SUNSET_HOUR = 18.0

    _EPS = 1e-6

    def __init__(
        self,
        rated_cooling_kw: float | None = None,
        rated_air_flow_m3h: float | None = None,
        vrf_rated_kw: float | None = None,
    ) -> None:
        """支持以构造参数覆写额定基准值，便于不同建筑规模复用。"""
        self.rated_cooling_kw = float(rated_cooling_kw) if rated_cooling_kw else self.RATED_COOLING_LOAD_KW
        self.rated_air_flow_m3h = float(rated_air_flow_m3h) if rated_air_flow_m3h else self.RATED_AIR_FLOW_M3H
        self.vrf_rated_kw = float(vrf_rated_kw) if vrf_rated_kw else self.VRF_RATED_LOAD_KW

    # ────────────────────────── 水侧 ──────────────────────────
    def calc_water_side(self, cooling_load: float, supply_temp: float) -> dict[str, Any]:
        """冷冻水环路过程量反算（Q=c·m·ΔT + 水泵相似律）。"""
        try:
            load_kw = max(0.0, float(cooling_load))
            t_supply = float(supply_temp)
            t_return = t_supply + 5.0
            delta_t = max(self._EPS, t_return - t_supply)

            mass_flow_kgs = (load_kw * 1.0) / (self.CP_WATER_KJ * delta_t)
            flow_m3h = mass_flow_kgs * 3600.0 / max(self._EPS, self.RHO_WATER)

            plr = min(1.2, load_kw / max(self._EPS, self.rated_cooling_kw))

            rated_flow_m3h = (self.rated_cooling_kw * 1.0) / (self.CP_WATER_KJ * 5.0) * 3600.0 / self.RHO_WATER
            flow_ratio = flow_m3h / max(self._EPS, rated_flow_m3h)
            worst_loop_dp_kpa = self.RATED_LOOP_DP_KPA * (flow_ratio ** 2)

            valve_open = 0.30 + 0.70 * min(1.0, max(0.0, plr))
            valve_open_pct = float(np.clip(valve_open * 100.0, 10.0, 100.0))

            pump_freq_hz = float(np.clip(
                self.PUMP_RATED_FREQ_HZ * flow_ratio,
                self.PUMP_MIN_FREQ_HZ,
                self.PUMP_RATED_FREQ_HZ,
            ))

            pump_head_m = worst_loop_dp_kpa / max(self._EPS, self.GRAVITY)

            return {
                "cooling_load_kw": round(load_kw, 2),
                "supply_temp_c": round(t_supply, 2),
                "return_temp_c": round(t_return, 2),
                "delta_t_k": round(delta_t, 2),
                "plr_ratio": round(plr, 3),
                "mass_flow_kgs": round(mass_flow_kgs, 3),
                "flow_m3h": round(flow_m3h, 2),
                "worst_loop_dp_kpa": round(worst_loop_dp_kpa, 2),
                "valve_opening_avg_pct": round(valve_open_pct, 1),
                "pump_freq_hz": round(pump_freq_hz, 2),
                "pump_head_m": round(pump_head_m, 2),
            }
        except Exception as exc:
            _logger.exception("calc_water_side failed")
            return {
                "flow_m3h": 0.0,
                "worst_loop_dp_kpa": 0.0,
                "valve_opening_avg_pct": 0.0,
                "pump_freq_hz": self.PUMP_MIN_FREQ_HZ,
                "pump_head_m": 0.0,
                "error": f"calc_water_side 异常：{type(exc).__name__}",
            }

    # ────────────────────────── 风侧 ──────────────────────────
    def calc_air_side(self, zone_loads: dict) -> dict[str, Any]:
        """风侧 VAV 系统过程量反算（Q=ρ·cp·V·ΔT + 风机相似律）。"""
        try:
            if not isinstance(zone_loads, dict) or not zone_loads:
                zone_loads = {}

            zone_flow_m3h: dict[str, float] = {}
            zone_flow_max_m3h: dict[str, float] = {}
            for zk, q_kw in zone_loads.items():
                q = max(0.0, float(q_kw))
                v_m3h = q / max(self._EPS, self.RHO_CP_AIR * self.DELTA_T_AIR_K) * 3600.0
                zone_flow_m3h[zk] = v_m3h
                zone_flow_max_m3h[zk] = max(self._EPS, v_m3h * 1.4 + 1.0)

            total_flow_m3h = float(sum(zone_flow_m3h.values()))

            vav_openings_pct: dict[str, float] = {}
            for zk, v in zone_flow_m3h.items():
                ratio = v / zone_flow_max_m3h[zk]
                vav_openings_pct[zk] = round(float(np.clip(ratio * 100.0, 10.0, 100.0)), 1)

            flow_ratio = total_flow_m3h / max(self._EPS, self.rated_air_flow_m3h)
            flow_ratio_clip = float(np.clip(flow_ratio, 0.2, 1.2))
            duct_static_pa = (
                self.DUCT_STATIC_MIN_PA
                + (self.DUCT_STATIC_MAX_PA - self.DUCT_STATIC_MIN_PA) * min(1.0, flow_ratio_clip)
            )

            fan_freq_hz = float(np.clip(
                self.FAN_RATED_FREQ_HZ * flow_ratio,
                self.FAN_MIN_FREQ_HZ,
                self.FAN_RATED_FREQ_HZ,
            ))

            return {
                "zone_flow_m3h": {k: round(v, 1) for k, v in zone_flow_m3h.items()},
                "vav_openings_pct": vav_openings_pct,
                "total_air_flow_m3h": round(total_flow_m3h, 1),
                "duct_static_pressure_pa": round(duct_static_pa, 1),
                "fan_freq_hz": round(fan_freq_hz, 2),
                "supply_air_delta_t_k": round(self.DELTA_T_AIR_K, 1),
            }
        except Exception as exc:
            _logger.exception("calc_air_side failed")
            return {
                "vav_openings_pct": {},
                "duct_static_pressure_pa": self.DUCT_STATIC_MIN_PA,
                "fan_freq_hz": self.FAN_MIN_FREQ_HZ,
                "error": f"calc_air_side 异常：{type(exc).__name__}",
            }

    # ──────────────────────── 多联机 VRF ────────────────────────
    def calc_vrf_side(self, vrf_load: float) -> dict[str, Any]:
        """多联机 VRF 过程量反算：Q = m_dot·Δh + EXV(PLR)。"""
        try:
            load_kw = max(0.0, float(vrf_load))
            plr = min(1.2, load_kw / max(self._EPS, self.vrf_rated_kw))

            mass_flow_kgs = load_kw / max(self._EPS, self.R410A_LATENT_KJ)
            mass_flow_kgh = mass_flow_kgs * 3600.0

            exv_raw = self.EXV_BASE_OPENING_PCT + self.EXV_GAIN_PCT * min(1.0, max(0.0, plr))
            exv_pct = float(np.clip(exv_raw, self.EXV_MIN_PCT, self.EXV_MAX_PCT))

            evap_temp_c = round(7.0 - 2.0 * min(1.0, plr), 2)

            return {
                "vrf_load_kw": round(load_kw, 2),
                "plr_ratio": round(plr, 3),
                "exv_opening_pct": round(exv_pct, 1),
                "refrigerant_mass_flow_kgh": round(mass_flow_kgh, 2),
                "refrigerant_mass_flow_kgs": round(mass_flow_kgs, 4),
                "evap_temp_c": evap_temp_c,
                "refrigerant_enthalpy_kj_kg": self.R410A_LATENT_KJ,
            }
        except Exception as exc:
            _logger.exception("calc_vrf_side failed")
            return {
                "exv_opening_pct": self.EXV_MIN_PCT,
                "refrigerant_mass_flow_kgh": 0.0,
                "error": f"calc_vrf_side 异常：{type(exc).__name__}",
            }

    # ──────────────────────── 环境扰动 ────────────────────────
    def calc_env_disturbance(
        self,
        t_out: float = 32.0,
        hour: float = 14.0,
        building_area_m2: float = 10000.0,
        window_ratio: float = 0.3,
        cloud_cover: float = 0.0,
        solar_hour_angle_deg: float | None = None,
    ) -> dict[str, Any]:
        """环境扰动冷负荷估算（太阳常数 1353 W/m² 为基准）。"""
        try:
            t_out_v = float(t_out)
            hour_v = float(hour)
            area = max(0.0, float(building_area_m2))
            wwr = float(np.clip(window_ratio, 0.0, 1.0))
            cloud = float(np.clip(cloud_cover, 0.0, 1.0))

            if solar_hour_angle_deg is not None:
                sin_beta = max(0.0, math.cos(math.radians(float(solar_hour_angle_deg))))
            else:
                if self.SUNRISE_HOUR <= hour_v <= self.SUNSET_HOUR:
                    sin_beta = math.sin(
                        math.pi * (hour_v - self.SUNRISE_HOUR)
                        / max(self._EPS, (self.SUNSET_HOUR - self.SUNRISE_HOUR))
                    )
                    sin_beta = max(0.0, sin_beta)
                else:
                    sin_beta = 0.0

            irradiance_wm2 = self.SOLAR_CONSTANT * self.ATMOS_TRANSMISSIVITY * sin_beta * (1.0 - cloud)

            building_height_m = 4.5
            envelope_area_m2 = math.sqrt(max(0.0, area)) * building_height_m * 4.0

            q_solar_w = irradiance_wm2 * envelope_area_m2 * wwr * self.ENVELOPE_GAIN_COEFF
            q_cond_w = (
                self.OPAQUE_U_W_M2K * envelope_area_m2 * (1.0 - wwr)
                * max(0.0, t_out_v - self.INDOOR_SET_TEMP_C)
            )

            disturbance_load_kw = (q_solar_w + q_cond_w) / 1000.0

            return {
                "solar_constant_wm2": self.SOLAR_CONSTANT,
                "solar_irradiance_wm2": round(irradiance_wm2, 1),
                "sin_solar_altitude": round(sin_beta, 3),
                "atmos_transmissivity": self.ATMOS_TRANSMISSIVITY,
                "envelope_area_m2": round(envelope_area_m2, 1),
                "window_to_wall_ratio": round(wwr, 2),
                "cloud_cover": round(cloud, 2),
                "outdoor_temp_c": round(t_out_v, 2),
                "indoor_set_temp_c": self.INDOOR_SET_TEMP_C,
                "q_solar_kw": round(q_solar_w / 1000.0, 2),
                "q_conduction_kw": round(q_cond_w / 1000.0, 2),
                "disturbance_load_kw": round(disturbance_load_kw, 2),
            }
        except Exception as exc:
            _logger.exception("calc_env_disturbance failed")
            return {
                "solar_constant_wm2": self.SOLAR_CONSTANT,
                "solar_irradiance_wm2": 0.0,
                "disturbance_load_kw": 0.0,
                "error": f"calc_env_disturbance 异常：{type(exc).__name__}",
            }

    # ──────────────────────── 室内热舒适（PMV）────────────────────────
    def calc_pmv(
        self,
        temp: float,
        relative_humidity: float = 50,
        air_speed: float = 0.15,
        clo: float = 0.5,
        met: float = 1.1,
    ) -> float:
        """ISO 7730 / ASHRAE 55 标准 PMV 计算（Fanger 1972 完整迭代实现）。"""
        try:
            ta = float(temp)
            rh = float(relative_humidity)
            vel = max(0.0, float(air_speed))
            clo_v = max(0.0, float(clo))
            met_v = max(0.8, float(met))

            tr = ta
            M = met_v * 58.15
            W_ext = 0.0
            Icl = clo_v * 0.155

            if Icl <= 0.078:
                fcl = 1.0 + 1.29 * Icl
            else:
                fcl = 1.05 + 0.645 * Icl

            pa = rh * 10.0 * math.exp(16.6536 - 4030.183 / (ta + 235.0))
            hcf = 12.1 * math.sqrt(vel)

            tcl = ta + (35.5 - ta) / (3.5 * (Icl + 0.1))
            hc = hcf
            for _ in range(150):
                hcn = 2.38 * abs(tcl - ta) ** 0.25
                hc = hcf if hcf > hcn else hcn
                tcl_new = (
                    35.7 - 0.028 * (M - W_ext) - Icl * (
                        3.96e-8 * fcl * ((tcl + 273.0) ** 4 - (tr + 273.0) ** 4)
                        + fcl * hc * (tcl - ta)
                    )
                )
                if abs(tcl_new - tcl) < 1e-4:
                    tcl = tcl_new
                    break
                tcl = tcl_new

            hl1 = 3.05e-3 * (5733.0 - 6.99 * (M - W_ext) - pa)
            hl2 = 0.42 * ((M - W_ext) - 58.15) if (M - W_ext) > 58.15 else 0.0
            hl3 = 1.7e-5 * M * (5867.0 - pa)
            hl4 = 0.0014 * M * (34.0 - ta)
            hl5 = 3.96e-8 * fcl * ((tcl + 273.0) ** 4 - (tr + 273.0) ** 4)
            hl6 = fcl * hc * (tcl - ta)

            ts = 0.303 * math.exp(-0.036 * M) + 0.028
            pmv = ts * ((M - W_ext) - hl1 - hl2 - hl3 - hl4 - hl5 - hl6)
            return float(pmv)
        except Exception:
            _logger.exception("calc_pmv failed")
            return 0.0

    # ──────────────────────── 聚合入口 ────────────────────────
    def simulate_all(
        self,
        cooling_load_kw: float,
        supply_temp_c: float,
        zone_loads: dict,
        vrf_load_kw: float,
        t_out: float = 32.0,
        hour: float = 12.0,
        building_area_m2: float = 12000.0,
        window_ratio: float = 0.65,
        cloud_cover: float = 0.0,
        indoor_temp_c: float = 26.0,
        indoor_rh_percent: float = 50.0,
        indoor_air_speed_ms: float = 0.15,
        occupant_clo: float = 0.5,
        occupant_met: float = 1.1,
    ) -> dict[str, Any]:
        """一次性串联水侧 / 风侧 / VRF / 环境扰动 4 类过程量反算并扁平化输出。"""
        try:
            water = self.calc_water_side(cooling_load_kw, supply_temp_c)
            air = self.calc_air_side(zone_loads or {})
            vrf = self.calc_vrf_side(vrf_load_kw)
            env = self.calc_env_disturbance(
                t_out=t_out, hour=hour,
                building_area_m2=building_area_m2,
                window_ratio=window_ratio,
                cloud_cover=cloud_cover,
            )
            try:
                pmv_value = round(float(self.calc_pmv(
                    temp=indoor_temp_c, relative_humidity=indoor_rh_percent,
                    air_speed=indoor_air_speed_ms,
                    clo=occupant_clo, met=occupant_met,
                )), 2)
            except Exception:
                _logger.exception("simulate_all: calc_pmv failed")
                pmv_value = 0.0
            return {
                # 4 个核心物理量
                "pump_freq_hz": water.get("pump_freq_hz"),
                "duct_static_pressure_pa": air.get("duct_static_pressure_pa"),
                "exv_opening_pct": vrf.get("exv_opening_pct"),
                "worst_loop_dp_kpa": water.get("worst_loop_dp_kpa"),
                # 水侧扩展
                "chw_flow_m3h": water.get("flow_m3h"),
                "valve_opening_avg_pct": water.get("valve_opening_avg_pct"),
                "pump_head_m": water.get("pump_head_m"),
                "chw_supply_temp_c": water.get("supply_temp_c"),
                "chw_return_temp_c": water.get("return_temp_c"),
                # 风侧扩展
                "total_air_flow_m3h": air.get("total_air_flow_m3h"),
                "fan_freq_hz": air.get("fan_freq_hz"),
                "vav_openings_pct": air.get("vav_openings_pct"),
                # VRF 扩展
                "refrigerant_mass_flow_kgh": vrf.get("refrigerant_mass_flow_kgh"),
                "evap_temp_c": vrf.get("evap_temp_c"),
                "vrf_plr": vrf.get("plr_ratio"),
                # 环境扰动扩展
                "solar_irradiance_wm2": env.get("solar_irradiance_wm2"),
                "disturbance_load_kw": env.get("disturbance_load_kw"),
                "outdoor_temp_c": env.get("outdoor_temp_c"),
                "solar_constant_wm2": env.get("solar_constant_wm2"),
                # 完整子状态
                "_water": water,
                "_air": air,
                "_vrf": vrf,
                "_env": env,
                # 室内热舒适
                "PMV_Index": pmv_value,
                "indoor_temp_c": round(float(indoor_temp_c), 2),
                "indoor_rh_percent": round(float(indoor_rh_percent), 1),
            }
        except Exception as exc:
            _logger.exception("simulate_all failed")
            return {
                "error": f"simulate_all 异常：{type(exc).__name__}: {exc}",
                "pump_freq_hz": 0.0,
                "duct_static_pressure_pa": 0.0,
                "exv_opening_pct": 0.0,
                "worst_loop_dp_kpa": 0.0,
                "PMV_Index": 0.0,
            }


__all__ = ["PhysicsSimulationEngine"]
