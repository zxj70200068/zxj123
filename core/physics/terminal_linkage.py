"""Terminal point-ledger linkage analysis."""

from __future__ import annotations

import math
from typing import Any


class TerminalPointLinkageModel:
    """房间/区域末端测点联动仿真：支持区域级参数和房间/支路/点位台账参数。"""

    def __init__(
        self,
        zone_specs: dict,
        sys_config: dict,
        last_res: dict | None = None,
        point_ledger: dict | None = None,
    ) -> None:
        self.zone_specs = zone_specs
        self.sys_config = sys_config
        self.last_res = last_res or {}
        self.point_ledger = point_ledger or {}
        self.dn_sizes: dict[str, float] = {
            "DN300": 0.30, "DN250": 0.25, "DN200": 0.20, "DN150": 0.15, "DN125": 0.125,
            "DN100": 0.10, "DN80": 0.08, "DN65": 0.065, "DN50": 0.05, "DN40": 0.04, "DN32": 0.032,
        }

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def _current_zone_cooling_kw(self, zone_name: str, default_kw: float) -> float:
        hyd = self.last_res.get("hydraulic", {}) if isinstance(self.last_res, dict) else {}
        for b in hyd.get("branches", []):
            if b.get("zone_name") == zone_name and b.get("cooling_kw", 0) > 0:
                return float(b.get("cooling_kw", default_kw))
        return default_kw

    def available_targets(self) -> list[str]:
        items = list(self.zone_specs.keys())
        for rid, room in self.point_ledger.get("rooms", {}).items():
            label = f"{rid} | {room.get('room_name', rid)}"
            if label not in items:
                items.append(label)
        return items

    def _resolve_target(self, target_name: str) -> tuple[str, str | None, dict | None]:
        rooms = self.point_ledger.get("rooms", {})
        zones = self.point_ledger.get("zones", {})
        room_id: str | None = None
        room_cfg: dict | None = None
        target_key = target_name.split(" | ", 1)[0] if " | " in target_name else target_name
        if target_key in rooms:
            room_id, room_cfg = target_key, rooms[target_key]
        else:
            for rid, rcfg in rooms.items():
                if target_name == rcfg.get("room_name"):
                    room_id, room_cfg = rid, rcfg
                    break
        if room_cfg:
            zone_id = room_cfg.get("zone_id")
            zone_name = zones.get(zone_id, {}).get("zone_name", zone_id)
            if zone_name not in self.zone_specs:
                # 如果台账中的区域尚未进入主建筑配置，构造一个临时区域配置用于分析
                z_ledger = zones.get(zone_id, {})
                design_load = float(room_cfg.get("design_load_kw", z_ledger.get("design_load_kw", 1000)))
                self.zone_specs.setdefault(zone_name, {
                    "area_type": z_ledger.get("area_type", "公共"),
                    "system_type": z_ledger.get("system_type", room_cfg.get("serve_system", "CHW")),
                    "design_load_kw": design_load,
                    "terminal_type": room_cfg.get("terminal_type", z_ledger.get("terminal_type", "末端设备")),
                    "pipe_dn": "DN100", "pipe_length_m": 100.0, "terminal_dp_kpa": 35.0,
                    "air_duct_area_m2": 1.2,
                    "air_duct_length_m": 35.0,
                    "air_resistance_coeff": 0.9,
                    "fan_efficiency": 0.60,
                    "design_airflow_m3h": design_load * 250.0,
                })
            return zone_name, room_id, room_cfg
        return target_name, None, None

    def _find_branch(
        self,
        section: str,
        room_id: str | None = None,
        zone_name: str | None = None,
    ) -> tuple[str | None, dict]:
        data = self.point_ledger.get(section, {})
        zones = self.point_ledger.get("zones", {})
        if room_id:
            for bid, br in data.items():
                if br.get("room_id") == room_id:
                    return bid, br
        if zone_name:
            for bid, br in data.items():
                zid = br.get("zone_id")
                if zones.get(zid, {}).get("zone_name") == zone_name:
                    return bid, br
        return None, {}

    def _linked_points(self, object_id: str) -> list[tuple[str, dict]]:
        pts: list[tuple[str, dict]] = []
        for pid, p in self.point_ledger.get("bas_points", {}).items():
            if p.get("linked_object_id") == object_id:
                pts.append((pid, p))
        return pts

    def analyze_zone(self, zone_name: str, overrides: dict | None = None) -> list[dict]:
        overrides = overrides or {}
        resolved_zone, room_id, room_cfg = self._resolve_target(zone_name)
        z_cfg = dict(self.zone_specs.get(resolved_zone, {}))
        if room_cfg:
            z_cfg["design_load_kw"] = float(room_cfg.get("design_load_kw", z_cfg.get("design_load_kw", 1000.0)))
            z_cfg["terminal_type"] = room_cfg.get("terminal_type", z_cfg.get("terminal_type", "末端设备"))
            z_cfg["design_airflow_m3h"] = float(
                room_cfg.get(
                    "design_airflow_m3h",
                    z_cfg.get("design_airflow_m3h", z_cfg.get("design_load_kw", 1000.0) * 250.0),
                )
            )
        chw_id, chw_branch = self._find_branch("chw_branches", room_id, resolved_zone)
        air_id, air_branch = self._find_branch("air_branches", room_id, resolved_zone)
        cw_id, cw_branch = self._find_branch("cw_branches")

        # 台账支路参数优先级高于区域默认参数
        if chw_branch:
            z_cfg["pipe_dn"] = chw_branch.get("pipe_dn", z_cfg.get("pipe_dn", "DN100"))
            z_cfg["pipe_length_m"] = float(chw_branch.get("pipe_length_m", z_cfg.get("pipe_length_m", 100.0)))
            z_cfg["terminal_dp_kpa"] = float(chw_branch.get("terminal_dp_kpa", z_cfg.get("terminal_dp_kpa", 35.0)))
        if air_branch:
            z_cfg["air_duct_area_m2"] = float(air_branch.get("duct_area_m2", z_cfg.get("air_duct_area_m2", 1.2)))
            z_cfg["air_duct_length_m"] = float(air_branch.get("duct_length_m", z_cfg.get("air_duct_length_m", 35.0)))
            z_cfg["air_resistance_coeff"] = float(
                air_branch.get("air_resistance_coeff", z_cfg.get("air_resistance_coeff", 0.9))
            )
            z_cfg["design_airflow_m3h"] = float(
                air_branch.get(
                    "design_airflow_m3h",
                    z_cfg.get("design_airflow_m3h", z_cfg.get("design_load_kw", 1000.0) * 250.0),
                )
            )

        design_kw = float(z_cfg.get("design_load_kw", 1000.0))
        terminal_type = z_cfg.get("terminal_type", "末端设备")
        dn = z_cfg.get("pipe_dn", "DN100")
        diameter_m = self.dn_sizes.get(dn, 0.10)
        pipe_length_m = float(z_cfg.get("pipe_length_m", 100.0))
        terminal_dp_kpa = float(z_cfg.get("terminal_dp_kpa", 35.0))
        cooling_kw_default = self._current_zone_cooling_kw(resolved_zone, design_kw * 0.7)

        rows: list[dict] = []

        def add(category: str, name: str, value: Any, unit: str, note: str) -> None:
            rows.append({"category": category, "name": name, "value": value, "unit": unit, "note": note})

        add("台账索引", "分析对象", zone_name, "-", f"解析区域={resolved_zone}；房间ID={room_id or '-'}")
        if chw_id:
            add("台账索引", "冷冻水管路编号", chw_id, "-", chw_branch.get("remarks", "来自冷冻水管路台账"))
        if air_id:
            add("台账索引", "风管编号", air_id, "-", air_branch.get("remarks", "来自风管系统台账"))
        if cw_id:
            add("台账索引", "冷却水管路编号", cw_id, "-", cw_branch.get("remarks", "来自冷却水系统台账"))

        # 冷冻水系统
        chw_delta_t = 5.0
        default_branch_flow = float(chw_branch.get("design_flow_m3h", 0)) if chw_branch else 0.0
        flow_default = (
            default_branch_flow
            if default_branch_flow > 0
            else (cooling_kw_default / (1.163 * chw_delta_t) if chw_delta_t > 0 else 0.0)
        )
        chw_flow_m3h = max(0.0, self._to_float(overrides.get("chilled_water_flow_m3h"), flow_default))
        chw_flow_m3s = chw_flow_m3h / 3600.0
        pipe_area = math.pi * (diameter_m ** 2) / 4.0
        water_velocity = chw_flow_m3s / pipe_area if pipe_area > 0 else 0.0
        friction_coeff = float(chw_branch.get("friction_coeff", 0.08)) if chw_branch else 0.08
        local_coeff = float(chw_branch.get("local_loss_coeff", 5.0)) if chw_branch else 5.0
        friction_loss_kpa = pipe_length_m * friction_coeff * (water_velocity ** 2)
        local_loss_kpa = local_coeff * (water_velocity ** 2)
        branch_dp_kpa = friction_loss_kpa + local_loss_kpa + terminal_dp_kpa
        chw_cooling_kw = 1.163 * chw_flow_m3h * chw_delta_t
        valve_opening = (
            min(100.0, max(0.0, (chw_cooling_kw / design_kw) * 100.0))
            if design_kw > 0 else 0.0
        )
        pump_power_kw = (
            chw_flow_m3h * (branch_dp_kpa / 9.81) / (367.0 * 0.72)
            if branch_dp_kpa > 0 else 0.0
        )
        chiller_power_delta = chw_cooling_kw / 5.5 if chw_cooling_kw > 0 else 0.0

        add("冷冻水管", "区域/末端类型", f"{resolved_zone} / {terminal_type}", "-", "当前选择的区域、房间或末端形式")
        add("冷冻水管", "供水温度",
            float(chw_branch.get("supply_temp_c", 7.0)) if chw_branch else 7.0, "℃", "冷冻水供水侧温度表")
        add("冷冻水管", "回水温度",
            float(chw_branch.get("return_temp_c", 12.0)) if chw_branch else 12.0, "℃", "冷冻水回水侧温度表")
        add("冷冻水管", "冷冻水流量", round(chw_flow_m3h, 2), "m³/h", "可修改；由冷量与供回水温差联动")
        add("冷冻水管", "管径", dn, "-", "来自建筑配置或冷冻水管路台账")
        add("冷冻水管", "管内流速", round(water_velocity, 3), "m/s", "v=G/A，流量变化会同步改变流速")
        add("冷冻水管", "沿程阻力", round(friction_loss_kpa, 3), "kPa", "按速度平方型模型估算")
        add("冷冻水管", "局部阻力", round(local_loss_kpa, 3), "kPa", "按局部构件阻力估算")
        add("冷冻水管", "末端压差", round(terminal_dp_kpa, 2), "kPa", "来自末端设备配置或管路台账")
        add("冷冻水管", "支路总阻力", round(branch_dp_kpa, 3), "kPa", "沿程+局部+末端压差")
        add("冷冻水管", "阀门开度", round(valve_opening, 1), "%", "按当前交付冷量占设计冷量估算")
        add("冷冻水管", "末端交付冷量", round(chw_cooling_kw, 2), "kW", "Q=1.163×G×ΔT")
        add("冷冻水管", "水泵功率贡献", round(pump_power_kw, 3), "kW", "P=流量×扬程/(367×效率)")
        add("机组影响", "冷机功率变化估算", round(chiller_power_delta, 2), "kW", "按等效COP=5.5估算该末端冷量对应冷机功率")

        # 风系统
        air_area = max(0.05, self._to_float(overrides.get("air_duct_area_m2"), float(z_cfg.get("air_duct_area_m2", 1.2))))
        air_length = float(z_cfg.get("air_duct_length_m", 35.0))
        air_k = float(z_cfg.get("air_resistance_coeff", 0.9))
        fan_eff = max(0.1, float(z_cfg.get("fan_efficiency", 0.60)))
        design_airflow = float(z_cfg.get("design_airflow_m3h", design_kw * 250.0))
        airflow_m3h = max(0.0, self._to_float(overrides.get("airflow_m3h"), design_airflow * 0.7))
        airflow_m3s = airflow_m3h / 3600.0
        air_velocity = airflow_m3s / air_area if air_area > 0 else 0.0
        local_loss_coeff = float(air_branch.get("local_loss_coeff", 30.0)) if air_branch else 30.0
        air_pressure_loss = air_length * air_k * (air_velocity ** 2)
        air_local_loss = local_loss_coeff * (air_velocity ** 2)
        outlet_loss = 80.0
        total_air_dp = air_pressure_loss + air_local_loss + outlet_loss
        fan_power_kw = (
            airflow_m3s * total_air_dp / fan_eff / 1000.0
            if fan_eff > 0 else 0.0
        )
        supply_air_temp = (
            float(air_branch.get(
                "supply_air_temp_c",
                room_cfg.get("supply_air_temp_c", 14.0) if room_cfg else 14.0,
            )) if air_branch else 14.0
        )
        return_air_temp = (
            float(air_branch.get(
                "return_air_temp_c",
                room_cfg.get("return_air_temp_c", 26.0) if room_cfg else 26.0,
            )) if air_branch else 26.0
        )
        # 风侧显热冷量：Q = ρ·cp·V·ΔT / 1000；ρ·cp/1000 ≈ 1.2 工程近似。
        air_cooling_kw = 1.2 * airflow_m3s * max(0.0, return_air_temp - supply_air_temp)

        add("风管", "送风量", round(airflow_m3h, 1), "m³/h", "可修改；影响风速、风阻和风机功率")
        add("风管", "风管截面积", round(air_area, 3), "m²", "可修改；截面积变小会提高风速")
        add("风管", "风速", round(air_velocity, 3), "m/s", "v=风量/截面积")
        add("风管", "沿程风阻", round(air_pressure_loss, 2), "Pa", "按长度与速度平方估算")
        add("风管", "局部风阻", round(air_local_loss, 2), "Pa", "弯头、阀件等局部阻力估算")
        add("风管", "末端风口阻力", outlet_loss, "Pa", "默认风口/末端阻力")
        add("风管", "总风压", round(total_air_dp, 2), "Pa", "沿程+局部+风口阻力")
        add("风管", "风机功率", round(fan_power_kw, 3), "kW", "P=风量×风压/效率")
        add("风管", "送风温度", supply_air_temp, "℃", "末端送风侧温度表")
        add("风管", "回风温度", return_air_temp, "℃", "末端回风侧温度表")
        add("风管", "风侧交付冷量", round(air_cooling_kw, 2), "kW", "约按ρcpVΔT估算")
        add("机组影响", "风机功率变化", round(fan_power_kw, 3), "kW", "送风量或风阻增加会提高风机耗电")

        # 冷却水系统
        cw_supply_temp = self._to_float(
            overrides.get("cooling_water_supply_temp"),
            float(cw_branch.get("cw_supply_temp_c", 32.0)) if cw_branch else 32.0,
        )
        cw_return_temp = self._to_float(
            overrides.get("cooling_water_return_temp"),
            float(cw_branch.get("cw_return_temp_c", 37.0)) if cw_branch else 37.0,
        )
        cw_flow_default = float(cw_branch.get("design_flow_m3h", 0)) if cw_branch else 0.0
        if cw_flow_default <= 0:
            cw_flow_default = max(1.0, 1.2 * chw_flow_m3h)
        cw_flow_m3h = max(0.0, self._to_float(overrides.get("cooling_water_flow_m3h"), cw_flow_default))
        condenser_heat_kw = chw_cooling_kw * 1.25
        cw_dn = cw_branch.get("pipe_dn", "DN200") if cw_branch else "DN200"
        cw_diameter = self.dn_sizes.get(cw_dn, 0.20)
        cw_area = math.pi * (cw_diameter ** 2) / 4.0
        cw_velocity = (cw_flow_m3h / 3600.0) / cw_area if cw_area > 0 else 0.0
        condenser_loop_dp_kpa = float(cw_branch.get("loop_dp_kpa", 120.0)) if cw_branch else 120.0
        cw_pump_power_kw = (
            cw_flow_m3h * (condenser_loop_dp_kpa / 9.81) / (367.0 * 0.70)
            if cw_flow_m3h > 0 else 0.0
        )
        cooling_tower_fan_power_kw = 0.015 * chw_cooling_kw
        base_cop = 5.5
        cop_corrected = max(1.0, base_cop * (1.0 - 0.02 * max(0.0, cw_supply_temp - 32.0)))
        chiller_power_kw = chw_cooling_kw / cop_corrected if cop_corrected > 0 else 0.0

        add("冷却水管", "冷却水供水温度", round(cw_supply_temp, 2), "℃", "可修改；升高会降低冷机COP")
        add("冷却水管", "冷却水回水温度", round(cw_return_temp, 2), "℃", "冷凝侧回水温度")
        add("冷却水管", "冷却水流量", round(cw_flow_m3h, 2), "m³/h", "可修改；影响冷凝侧换热和泵功率")
        add("冷却水管", "冷却水管径", cw_dn, "-", "冷却水系统台账管径")
        add("冷却水管", "冷却水流速", round(cw_velocity, 3), "m/s", "按冷却水管径估算")
        add("冷却水管", "冷却水泵扬程", condenser_loop_dp_kpa, "kPa", "冷凝水系统等效阻力")
        add("冷却水管", "冷却水泵功率", round(cw_pump_power_kw, 3), "kW", "冷却水流量增加会提高泵耗")
        add("冷却水管", "冷却塔风机功率", round(cooling_tower_fan_power_kw, 3), "kW", "按冷量比例估算")
        add("冷却水管", "冷凝侧换热量", round(condenser_heat_kw, 2), "kW", "约按蒸发器冷量×1.25估算")
        add("机组影响", "修正后冷机COP", round(cop_corrected, 3), "-", "冷却水供水温度每升高1℃，COP约下降2%")
        add("机组影响", "估算冷机功率", round(chiller_power_kw, 2), "kW", "冷机功率=末端冷量/修正COP")

        # BAS/DDC点位清单
        for obj_id in [chw_id, air_id, cw_id]:
            if not obj_id:
                continue
            for pid, point in self._linked_points(obj_id):
                add(
                    "BAS/DDC点位",
                    point.get("point_name", pid),
                    pid,
                    point.get("unit", "-"),
                    f"{point.get('system', '-')} | {point.get('measured_variable', '-')} | "
                    f"参与控制:{point.get('participate_control', '否')}",
                )

        return rows


__all__ = ["TerminalPointLinkageModel"]
