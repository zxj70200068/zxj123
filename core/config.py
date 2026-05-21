"""Configuration manager for the HVAC supervisory platform.

This module owns building, scenario, sequence-plan and point-ledger persistence.
LLM/API provider configuration is intentionally NOT loaded here; FEAT-004's
reporting service owns it. The constructor performs no Tk side effects and no
network IO.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any

from data.configs.defaults import (
    DEFAULT_BUILDING_CONFIGS,
    DEFAULT_POINT_LEDGER_TEMPLATE,
    DEFAULT_SCENARIOS,
    DEFAULT_SEQUENCE_PLAN,
    DEFAULT_SYS_CONFIG,
)
from utils.logging import get_logger
from utils.paths import PROJECT_ROOT

CONFIG_API_PATH = PROJECT_ROOT / "config_api.json"

_logger = get_logger(__name__)


class ConfigError(Exception):
    """Raised on configuration validation/IO failures.

    The legacy God File surfaced these errors via ``tkinter.messagebox`` from
    the GUI layer; the headless core layer raises this exception instead so
    the dialog code can live in the UI/services boundary.
    """


class ConfigManager:
    """Headless configuration manager (no Tk, no LLM IO).

    The constructor loads the in-memory defaults only. External JSON imports
    (buildings, scenarios, sequence plans, point ledgers) are explicit
    method calls; each ``load_external_*`` returns ``(ok, message[, extras])``
    so callers can decide whether to surface errors as dialogs or raise.
    Validation helpers may also be called directly and raise :class:`ConfigError`
    via :meth:`validate_or_raise` for code paths that prefer exceptions.
    """

    def __init__(self) -> None:
        self.sys_config: dict = json.loads(DEFAULT_SYS_CONFIG)
        self.scenarios: dict = DEFAULT_SCENARIOS.copy()
        self.building_configs: dict = DEFAULT_BUILDING_CONFIGS.copy()
        self.sequence_plan: list = list(DEFAULT_SEQUENCE_PLAN)
        # Deep-copy the point ledger template so mutations on the manager do
        # not leak into the module-level default.
        self.point_ledger: dict = json.loads(
            json.dumps(DEFAULT_POINT_LEDGER_TEMPLATE, ensure_ascii=False)
        )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def validate_or_raise(ok: bool, msg: str) -> None:
        """Helper: raise ``ConfigError`` if ``ok`` is False.

        Use this in code paths that prefer exceptions over the legacy
        ``(ok, msg)`` tuple convention.
        """
        if not ok:
            raise ConfigError(msg)

    # --------------------------------------------------------------- validate

    def validate_building_config(self, data: Any) -> tuple[bool, str]:
        if not isinstance(data, dict):
            return False, "建筑配置格式错误，必须为字典结构"
        for bk, b_cfg in data.items():
            if "zones" not in b_cfg or not isinstance(b_cfg["zones"], dict):
                return False, f"配置【{bk}】缺少 zones 字典"
            if "th" not in b_cfg or "tau" not in b_cfg:
                return False, f"建筑【{bk}】缺少 th 或 tau 参数"
            if b_cfg["tau"] <= 0:
                return False, f"建筑【{bk}】tau 必须为正数"
            if b_cfg["th"].get("high", 0) <= b_cfg["th"].get("mid", 0) or b_cfg["th"].get("mid", 0) <= 0:
                return False, f"建筑【{bk}】控制阈值必须满足 high > mid > 0"
            for zk, zv in b_cfg["zones"].items():
                if isinstance(zv, dict):
                    if "design_load_kw" not in zv:
                        return False, f"区域【{zk}】缺少 design_load_kw"
                    if zv["design_load_kw"] <= 0:
                        return False, f"区域【{zk}】design_load_kw 必须大于 0"
                    if "area_type" in zv and zv["area_type"] not in ["公共", "私域"]:
                        return False, f"区域【{zk}】area_type 必须为公共或私域"
                    if "system_type" in zv and zv["system_type"] not in ["CHW", "VRF", "BOTH", "NONE"]:
                        return False, f"区域【{zk}】system_type 必须为 CHW/VRF/BOTH/NONE"
                    if "pipe_length_m" in zv and zv["pipe_length_m"] <= 0:
                        return False, f"区域【{zk}】管路长度必须大于 0"
                    if "terminal_dp_kpa" in zv and zv["terminal_dp_kpa"] <= 0:
                        return False, f"区域【{zk}】末端压差必须大于 0"
                elif isinstance(zv, (int, float)):
                    if zv <= 0:
                        return False, f"区域【{zk}】负荷值必须大于 0"
                else:
                    return False, f"区域【{zk}】配置格式无法识别"
        return True, ""

    def validate_scenarios(self, data: Any) -> tuple[bool, str]:
        if not isinstance(data, dict):
            return False, "工况配置格式错误，必须为字典结构"
        required_keys = ["t_out", "r_zones", "c_sch", "c_occ", "is_night"]
        for sk, sv in data.items():
            for k in required_keys:
                if k not in sv:
                    return False, f"工况【{sk}】缺少字段 {k}"
            if not isinstance(sv["t_out"], (int, float)) or sv["t_out"] < -20 or sv["t_out"] > 60:
                return False, f"工况【{sk}】室外温度越界(-20~60)"
            if not (0 <= sv["c_sch"] <= 1):
                return False, f"工况【{sk}】c_sch 必须在 0~1 之间"
            if not (0 <= sv["c_occ"] <= 1):
                return False, f"工况【{sk}】c_occ 必须在 0~1 之间"
            if not isinstance(sv["is_night"], bool):
                return False, f"工况【{sk}】is_night 必须是布尔值"
            if isinstance(sv["r_zones"], list):
                if any(not isinstance(v, (int, float)) or v < 0 or v > 1 for v in sv["r_zones"]):
                    return False, f"工况【{sk}】r_zones 列表中的值必须在 0~1 之间"
            elif isinstance(sv["r_zones"], dict):
                if any(not isinstance(v, (int, float)) or v < 0 or v > 1 for v in sv["r_zones"].values()):
                    return False, f"工况【{sk}】r_zones 字典中的值必须在 0~1 之间"
            else:
                return False, f"工况【{sk}】r_zones 必须是列表或字典"
        return True, ""

    def validate_sequence_plan(self, data: Any) -> tuple[bool, str]:
        if not isinstance(data, list):
            return False, "时序计划格式错误，必须为数组"
        for idx, item in enumerate(data):
            if "scenario" not in item or "steps" not in item:
                return False, f"时序计划第 {idx + 1} 项缺少 scenario 或 steps"
            if not isinstance(item["steps"], int) or item["steps"] <= 0:
                return False, f"时序计划第 {idx + 1} 项 steps 必须为正整数"
            if item["scenario"] not in self.scenarios:
                return False, f"时序计划引用了不存在的工况【{item['scenario']}】"
        return True, ""

    def validate_point_ledger(self, data: Any) -> tuple[bool, str]:
        """校验机电台账：引用关系、重复点位、正数边界与可降级警告。"""
        if not isinstance(data, dict):
            return False, "测点台账格式错误，必须为字典结构"
        required_sections = [
            "building_profile", "zones", "rooms", "chw_branches",
            "air_branches", "cw_branches", "bas_points",
        ]
        for sec in required_sections:
            if sec not in data or not isinstance(data[sec], dict):
                return False, f"测点台账缺少 {sec} 字典"

        zones = data.get("zones", {})
        rooms = data.get("rooms", {})
        chw = data.get("chw_branches", {})
        air = data.get("air_branches", {})
        cw = data.get("cw_branches", {})
        points = data.get("bas_points", {})
        valid_dns = {"DN300", "DN250", "DN200", "DN150", "DN125", "DN100", "DN80", "DN65", "DN50"}

        for zid, z in zones.items():
            if not z.get("zone_name"):
                return False, f"区域 {zid} 缺少 zone_name"
            if z.get("area_type", "公共") not in ["公共", "私域"]:
                return False, f"区域 {zid} area_type 必须为公共或私域"
            if z.get("system_type", "CHW") not in ["CHW", "VRF", "BOTH", "NONE"]:
                return False, f"区域 {zid} system_type 必须为 CHW/VRF/BOTH/NONE"
            if float(z.get("design_load_kw", 1)) <= 0:
                return False, f"区域 {zid} design_load_kw 必须大于0"

        for rid, room in rooms.items():
            if "zone_id" not in room or "room_name" not in room:
                return False, f"房间 {rid} 缺少 zone_id 或 room_name"
            if room["zone_id"] not in zones:
                return False, f"房间 {rid} 绑定的 zone_id={room['zone_id']} 不存在"
            if float(room.get("design_load_kw", 0)) <= 0:
                return False, f"房间 {rid} design_load_kw 必须大于0"
            if float(room.get("design_airflow_m3h", 0)) <= 0:
                return False, f"房间 {rid} design_airflow_m3h 必须大于0"

        def check_branch_room(section_name: str, branches: dict) -> tuple[bool, str]:
            for bid, br in branches.items():
                room_id = br.get("room_id", "-")
                if room_id not in ["", "-"] and room_id not in rooms:
                    return False, f"{section_name} {bid} 绑定的 room_id={room_id} 不存在"
                zone_id = br.get("zone_id")
                if zone_id not in [None, "", "-", "Z-A00"] and zone_id not in zones:
                    return False, f"{section_name} {bid} 绑定的 zone_id={zone_id} 不存在"
            return True, ""

        ok, msg = check_branch_room("冷冻水管路", chw)
        if not ok:
            return False, msg
        ok, msg = check_branch_room("风管", air)
        if not ok:
            return False, msg

        for bid, br in chw.items():
            if br.get("pipe_dn", "DN100") not in valid_dns:
                _logger.warning(
                    "validate_point_ledger: 冷冻水管路 %s 未知管径 %s，运行时按 DN100 处理",
                    bid, br.get("pipe_dn"),
                )
            if float(br.get("pipe_length_m", 0)) < 0:
                return False, f"冷冻水管路 {bid} pipe_length_m 不得为负"
            if float(br.get("design_flow_m3h", 0)) < 0:
                return False, f"冷冻水管路 {bid} design_flow_m3h 不得为负"
            if float(br.get("terminal_dp_kpa", 0)) < 0:
                return False, f"冷冻水管路 {bid} terminal_dp_kpa 不得为负"

        for bid, br in air.items():
            if float(br.get("duct_area_m2", 0)) <= 0:
                return False, f"风管 {bid} duct_area_m2 必须大于0"
            if float(br.get("duct_length_m", 0)) < 0:
                return False, f"风管 {bid} duct_length_m 不得为负"
            if float(br.get("design_airflow_m3h", 0)) < 0:
                return False, f"风管 {bid} design_airflow_m3h 不得为负"

        for bid, br in cw.items():
            if br.get("pipe_dn", "DN200") not in valid_dns:
                _logger.warning(
                    "validate_point_ledger: 冷却水管路 %s 未知管径 %s，运行时按 DN200 处理",
                    bid, br.get("pipe_dn"),
                )
            if float(br.get("pipe_length_m", 0)) < 0:
                return False, f"冷却水管路 {bid} pipe_length_m 不得为负"
            if float(br.get("design_flow_m3h", 0)) < 0:
                return False, f"冷却水管路 {bid} design_flow_m3h 不得为负"
            if float(br.get("loop_dp_kpa", 0)) < 0:
                return False, f"冷却水管路 {bid} loop_dp_kpa 不得为负"

        seen_points: set = set()
        valid_objects = (
            set(rooms.keys()) | set(chw.keys()) | set(air.keys())
            | set(cw.keys()) | set(zones.keys())
        )
        for pid, pt in points.items():
            if pid in seen_points:
                return False, f"BAS/DDC点位 {pid} 重复"
            seen_points.add(pid)
            if "linked_object_id" not in pt or "measured_variable" not in pt:
                return False, f"点位 {pid} 缺少 linked_object_id 或 measured_variable"
            linked = pt.get("linked_object_id")
            if linked not in valid_objects:
                return False, f"点位 {pid} 关联对象 {linked} 不存在于房间/管路/区域台账"
        return True, ""

    # ---------------------------------------------------------------- loaders

    def load_external_config(self, file_path: str) -> tuple[bool, str, list]:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            loaded_keys: list = []
            if "building_configs" in data:
                ok, msg = self.validate_building_config(data["building_configs"])
                if not ok:
                    return False, msg, []
                self.building_configs.update(data["building_configs"])
                loaded_keys = list(data["building_configs"].keys())
            if "economics" in data:
                self.sys_config["economics"].update(data["economics"])
            if "equipment" in data:
                self.sys_config["equipment"].update(data["equipment"])
            if "safety" in data:
                self.sys_config["safety"].update(data["safety"])
            return True, "参数配置导入成功", loaded_keys
        except Exception as e:
            _logger.exception("ConfigManager.load_external_config failed")
            return False, f"导入配置失败: {e}", []

    def load_external_scenarios(self, file_path: str) -> tuple[bool, str]:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            ok, msg = self.validate_scenarios(data)
            if not ok:
                return False, msg
            self.scenarios = data
            return True, "环境工况导入成功"
        except Exception as e:
            _logger.exception("ConfigManager.load_external_scenarios failed")
            return False, f"导入工况失败: {e}"

    def load_external_sequence(self, file_path: str) -> tuple[bool, str]:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            ok, msg = self.validate_sequence_plan(data)
            if not ok:
                return False, msg
            self.sequence_plan = data
            return True, "时序计划导入成功"
        except Exception as e:
            _logger.exception("ConfigManager.load_external_sequence failed")
            return False, f"时序计划导入失败: {e}"

    def load_external_point_ledger(self, file_path: str) -> tuple[bool, str]:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            ok, msg = self.validate_point_ledger(data)
            if not ok:
                return False, msg
            self.point_ledger = data
            return True, "机电测点台账导入成功"
        except Exception as e:
            _logger.exception("ConfigManager.load_external_point_ledger failed")
            return False, f"导入测点台账失败: {e}"

    # ---------------------------------------------------------------- exports

    def export_point_ledger_template(self, file_path: str) -> tuple[bool, str]:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_POINT_LEDGER_TEMPLATE, f, indent=2, ensure_ascii=False)
            return True, "通用建筑机电测点台账模板已导出"
        except Exception as e:
            _logger.exception("ConfigManager.export_point_ledger_template failed")
            return False, f"导出模板失败: {e}"

    def export_point_ledger_csv_templates(self, folder_path: str) -> tuple[bool, str]:
        """将台账模板拆分为多个 CSV，便于 CAD/点表人员人工填写。"""
        try:
            os.makedirs(folder_path, exist_ok=True)
            section_to_file = {
                "zones": "zones.csv",
                "rooms": "rooms.csv",
                "chw_branches": "chw_branches.csv",
                "air_branches": "air_branches.csv",
                "cw_branches": "cw_branches.csv",
                "bas_points": "bas_points.csv",
            }
            for section, filename in section_to_file.items():
                data = DEFAULT_POINT_LEDGER_TEMPLATE.get(section, {})
                keys: set = set()
                for item in data.values():
                    if isinstance(item, dict):
                        keys.update(item.keys())
                headers = [section[:-1] + "_id"] + sorted(keys)
                with open(os.path.join(folder_path, filename), "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for item_id, item in data.items():
                        writer.writerow([item_id] + [item.get(h, "") for h in headers[1:]])
            readme = (
                "通用建筑机电测点台账CSV模板\n"
                "1. zones.csv：建筑区域表\n"
                "2. rooms.csv：房间末端表\n"
                "3. chw_branches.csv：冷冻水管路表\n"
                "4. air_branches.csv：风管系统表\n"
                "5. cw_branches.csv：冷却水系统表\n"
                "6. bas_points.csv：BAS/DDC点位表\n"
                "当前程序默认导入JSON台账；CSV模板用于CAD/BIM/点表整理与人工校核。\n"
            )
            with open(os.path.join(folder_path, "README.txt"), "w", encoding="utf-8") as f:
                f.write(readme)
            return True, f"CSV台账模板已导出至: {folder_path}"
        except Exception as e:
            _logger.exception("ConfigManager.export_point_ledger_csv_templates failed")
            return False, f"导出CSV模板失败: {e}"


__all__ = ["ConfigManager", "ConfigError", "CONFIG_API_PATH"]
