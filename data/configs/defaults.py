"""Default configuration constants extracted from the legacy God File.

These constants describe the out-of-the-box system, building, scenario, sequence
plan and point-ledger templates plus a few display name mappings used by the
UI/reporting layer. LLM/strategy registries are intentionally omitted here;
FEAT-004 will reintroduce a stripped LLM-providers-for-reporting variant under
``data/configs/llm_providers.py``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# DEFAULT_SYS_CONFIG: kept as a JSON triple-quoted string and parsed on demand
# via ``json.loads`` by callers (e.g. ConfigManager).
# ---------------------------------------------------------------------------
DEFAULT_SYS_CONFIG: str = """
{
    "economics": {
        "elec_price_flat": 0.8,
        "capex_diff_万元": 85.0,
        "maint_diff_万元": 2.5,
        "life_years": 15,
        "discount_rate": 0.05,
        "cooling_season_days": 150,
        "seasonal_load_coeff": 0.65,
        "tou_price": {
            "use_tou": true,
            "peak_price": 1.20,
            "flat_price": 0.80,
            "valley_price": 0.35,
            "peak_hours": [9, 10, 11, 14, 15, 16, 17, 18],
            "valley_hours": [23, 0, 1, 2, 3, 4, 5, 6]
        }
    },
    "equipment": {
        "chiller_total_units": 3,
        "capacity_central_kw": 7140.0,
        "capacity_vrf_kw": 4000.0,
        "capacity_base_kw": 7140.0
    },
    "safety": {
        "central_min_plr": 0.15,
        "vrf_min_plr": 0.10,
        "transformer_capacity_kva": 2500.0,
        "power_factor": 0.9,
        "min_run_minutes": 25,
        "min_stop_minutes": 15,
        "staging_lock_minutes": 15,
        "max_vrf_starts_per_hour": 4,
        "indoor_temp_limit": 26.5
    },
    "rc_model_params": {
        "heat_gain_coeff": 0.001,
        "envelope_ua_coeff": 0.015
    },
    "cop_tables": {
        "T_out": [25.0, 30.0, 35.0, 40.0, 45.0],
        "PLR": [0.05, 0.1, 0.4, 0.7, 1.0, 1.2],
        "central": [
            [3.5, 5.5, 8.8, 9.6, 8.2, 6.5],
            [3.0, 5.0, 8.2, 9.3, 7.8, 6.0],
            [2.5, 4.2, 7.5, 8.5, 7.2, 5.5],
            [1.8, 3.0, 5.5, 6.8, 5.8, 4.5],
            [1.2, 2.0, 4.0, 4.8, 4.2, 3.2]
        ],
        "vrf": [
            [2.2, 3.2, 4.2, 4.8, 4.5, 4.0],
            [2.0, 3.0, 4.0, 4.5, 4.2, 3.8],
            [1.8, 2.6, 3.6, 4.0, 3.8, 3.2],
            [1.2, 2.0, 2.8, 3.2, 3.0, 2.5],
            [0.8, 1.2, 2.0, 2.5, 2.2, 1.8]
        ],
        "base": [
            [1.5, 2.2, 3.2, 3.5, 3.2, 2.8],
            [1.2, 2.0, 3.0, 3.2, 3.0, 2.5],
            [1.0, 1.8, 2.8, 3.0, 2.8, 2.2],
            [0.8, 1.5, 2.2, 2.5, 2.2, 1.8],
            [0.5, 1.0, 1.5, 1.8, 1.5, 1.2]
        ]
    }
}
"""

DEFAULT_BUILDING_CONFIGS: dict = {
    "默认系统(通用公共建筑)": {
        "tau": 25,
        "th": {"high": 6000.0, "mid": 2200.0},
        "zones": {
            "公共大厅": {
                "area_type": "公共", "system_type": "CHW", "design_load_kw": 2500.0,
                "terminal_type": "AHU", "pipe_dn": "DN150", "pipe_length_m": 90.0, "terminal_dp_kpa": 35.0,
                "air_duct_area_m2": 1.50, "air_duct_length_m": 40.0, "air_resistance_coeff": 0.90,
                "fan_efficiency": 0.60, "design_airflow_m3h": 60000.0
            },
            "标准功能区": {
                "area_type": "公共", "system_type": "CHW", "design_load_kw": 3500.0,
                "terminal_type": "FCU+新风", "pipe_dn": "DN200", "pipe_length_m": 120.0, "terminal_dp_kpa": 35.0,
                "air_duct_area_m2": 1.20, "air_duct_length_m": 35.0, "air_resistance_coeff": 0.90,
                "fan_efficiency": 0.60, "design_airflow_m3h": 80000.0
            },
            "高人员密度区": {
                "area_type": "公共", "system_type": "BOTH", "design_load_kw": 1800.0,
                "terminal_type": "AHU/VRF混合", "pipe_dn": "DN125", "pipe_length_m": 80.0, "terminal_dp_kpa": 35.0,
                "air_duct_area_m2": 1.00, "air_duct_length_m": 30.0, "air_resistance_coeff": 1.00,
                "fan_efficiency": 0.60, "design_airflow_m3h": 50000.0
            },
            "设备机房": {
                "area_type": "私域", "system_type": "VRF", "design_load_kw": 300.0,
                "terminal_type": "精密空调/独立末端", "pipe_dn": "DN65", "pipe_length_m": 40.0, "terminal_dp_kpa": 25.0,
                "air_duct_area_m2": 0.50, "air_duct_length_m": 20.0, "air_resistance_coeff": 1.10,
                "fan_efficiency": 0.55, "design_airflow_m3h": 10000.0
            }
        }
    },
    "校园综合体示例": {
        "tau": 25,
        "th": {"high": 6000.0, "mid": 2200.0},
        "zones": {
            "教学区": {
                "area_type": "公共", "system_type": "CHW", "design_load_kw": 4500.0,
                "terminal_type": "组合式空调箱 AHU", "pipe_dn": "DN200", "pipe_length_m": 120.0, "terminal_dp_kpa": 35.0,
                "air_duct_area_m2": 1.80, "air_duct_length_m": 55.0, "air_resistance_coeff": 0.90,
                "fan_efficiency": 0.60, "design_airflow_m3h": 100000.0
            },
            "艺术中心": {
                "area_type": "公共", "system_type": "CHW", "design_load_kw": 1500.0,
                "terminal_type": "新风机组/FCU", "pipe_dn": "DN125", "pipe_length_m": 90.0, "terminal_dp_kpa": 35.0,
                "air_duct_area_m2": 1.00, "air_duct_length_m": 35.0, "air_resistance_coeff": 1.00,
                "fan_efficiency": 0.60, "design_airflow_m3h": 42000.0
            },
            "学生宿舍": {
                "area_type": "私域", "system_type": "VRF", "design_load_kw": 2000.0,
                "terminal_type": "风机盘管 FCU", "pipe_dn": "DN150", "pipe_length_m": 110.0, "terminal_dp_kpa": 35.0,
                "air_duct_area_m2": 0.80, "air_duct_length_m": 28.0, "air_resistance_coeff": 1.00,
                "fan_efficiency": 0.55, "design_airflow_m3h": 45000.0
            },
            "网络机房": {
                "area_type": "私域", "system_type": "VRF", "design_load_kw": 140.0,
                "terminal_type": "精密空调 CRAH", "pipe_dn": "DN50", "pipe_length_m": 45.0, "terminal_dp_kpa": 25.0,
                "air_duct_area_m2": 0.35, "air_duct_length_m": 16.0, "air_resistance_coeff": 1.20,
                "fan_efficiency": 0.55, "design_airflow_m3h": 8000.0
            }
        }
    }
}

DEFAULT_SCENARIOS: dict = {
    "01_上午运行高峰": {"t_out": 33.5, "r_zones": {"公共大厅": 0.85, "标准功能区": 1.0, "高人员密度区": 0.75, "设备机房": 0.6}, "c_sch": 1.0, "c_occ": 0.92, "is_night": False},
    "02_午间低谷": {"t_out": 36.5, "r_zones": {"公共大厅": 0.45, "标准功能区": 0.35, "高人员密度区": 0.55, "设备机房": 0.65}, "c_sch": 0.55, "c_occ": 0.60, "is_night": False},
    "03_下午高峰": {"t_out": 38.8, "r_zones": {"公共大厅": 0.9, "标准功能区": 0.85, "高人员密度区": 1.0, "设备机房": 0.7}, "c_sch": 0.95, "c_occ": 0.88, "is_night": False},
    "04_晚间局部运行": {"t_out": 30.0, "r_zones": {"公共大厅": 0.35, "标准功能区": 0.45, "高人员密度区": 0.2, "设备机房": 0.7}, "c_sch": 0.65, "c_occ": 0.55, "is_night": False},
    "05_夜间值班": {"t_out": 26.5, "r_zones": {"公共大厅": 0.05, "标准功能区": 0.05, "高人员密度区": 0.0, "设备机房": 1.0}, "c_sch": 0.1, "c_occ": 0.05, "is_night": True}
}

DEFAULT_SEQUENCE_PLAN: list = [
    {"scenario": "05_夜间值班", "steps": 24},
    {"scenario": "01_上午运行高峰", "steps": 16},
    {"scenario": "02_午间低谷", "steps": 12},
    {"scenario": "03_下午高峰", "steps": 24},
    {"scenario": "04_晚间局部运行", "steps": 20}
]

DEFAULT_POINT_LEDGER_TEMPLATE: dict = {
    "building_profile": {
        "building_id": "B001", "building_name": "通用公共建筑示例", "building_type": "public_building",
        "location": "Fujian", "cooling_season_days": 150,
        "note": "本模板由CAD/BIM/自控点表整理后导入；当前示例为可配置仿真台账。"
    },
    "zones": {
        "Z-A01": {"building_id": "B001", "zone_name": "公共大厅", "floor": "1F", "area_type": "公共", "system_type": "CHW", "area_m2": 1200, "design_load_kw": 2500, "terminal_type": "AHU", "remarks": "大空间公共区域"},
        "Z-A02": {"building_id": "B001", "zone_name": "标准功能区", "floor": "2F-5F", "area_type": "公共", "system_type": "CHW", "area_m2": 8000, "design_load_kw": 3500, "terminal_type": "FCU+新风", "remarks": "普通办公/教学/阅览空间"},
        "Z-A03": {"building_id": "B001", "zone_name": "高人员密度区", "floor": "3F", "area_type": "公共", "system_type": "BOTH", "area_m2": 1500, "design_load_kw": 1800, "terminal_type": "AHU/VRF混合", "remarks": "报告厅/会议厅/餐厅"},
        "Z-A04": {"building_id": "B001", "zone_name": "设备机房", "floor": "B1/屋面", "area_type": "私域", "system_type": "VRF", "area_m2": 300, "design_load_kw": 300, "terminal_type": "精密空调", "remarks": "信息机房/弱电机房"}
    },
    "rooms": {
        "R-A301": {"zone_id": "Z-A02", "room_name": "301标准房间", "floor": "3F", "room_type": "标准房间", "area_m2": 80, "design_load_kw": 18, "design_airflow_m3h": 2500, "terminal_type": "FCU+新风", "terminal_id": "FCU-A301", "serve_system": "CHW", "supply_air_temp_c": 14, "return_air_temp_c": 26, "remarks": "可代表普通教室/办公室"},
        "R-A302": {"zone_id": "Z-A02", "room_name": "302标准房间", "floor": "3F", "room_type": "标准房间", "area_m2": 75, "design_load_kw": 16, "design_airflow_m3h": 2200, "terminal_type": "FCU+新风", "terminal_id": "FCU-A302", "serve_system": "CHW", "supply_air_temp_c": 14, "return_air_temp_c": 26, "remarks": "普通房间支路示例"},
        "R-HALL01": {"zone_id": "Z-A01", "room_name": "一层公共大厅", "floor": "1F", "room_type": "大空间", "area_m2": 1200, "design_load_kw": 2500, "design_airflow_m3h": 60000, "terminal_type": "AHU", "terminal_id": "AHU-HALL01", "serve_system": "CHW", "supply_air_temp_c": 14, "return_air_temp_c": 26, "remarks": "大厅支路示例"},
        "R-MECH01": {"zone_id": "Z-A04", "room_name": "设备机房", "floor": "B1", "room_type": "机房", "area_m2": 120, "design_load_kw": 120, "design_airflow_m3h": 8000, "terminal_type": "精密空调", "terminal_id": "CRAH-MECH01", "serve_system": "VRF", "supply_air_temp_c": 18, "return_air_temp_c": 28, "remarks": "机房独立末端示例"}
    },
    "chw_branches": {
        "CHW-BR-A301": {"zone_id": "Z-A02", "room_id": "R-A301", "pipe_level": "terminal", "pipe_type": "supply", "pipe_dn": "DN50", "pipe_length_m": 38, "design_flow_m3h": 3.1, "design_velocity_ms": 0.65, "supply_temp_c": 7, "return_temp_c": 12, "terminal_dp_kpa": 28, "friction_coeff": 0.08, "local_loss_coeff": 5.0, "valve_id": "VLV-A301", "flow_meter_id": "FT-A301", "supply_pressure_sensor_id": "PT-A301-S", "return_pressure_sensor_id": "PT-A301-R", "supply_temp_sensor_id": "TT-A301-S", "return_temp_sensor_id": "TT-A301-R", "remarks": "301房间冷冻水支管"},
        "CHW-BR-HALL": {"zone_id": "Z-A01", "room_id": "R-HALL01", "pipe_level": "branch", "pipe_type": "supply", "pipe_dn": "DN150", "pipe_length_m": 90, "design_flow_m3h": 430, "design_velocity_ms": 1.8, "supply_temp_c": 7, "return_temp_c": 12, "terminal_dp_kpa": 35, "friction_coeff": 0.08, "local_loss_coeff": 5.0, "valve_id": "VLV-HALL", "flow_meter_id": "FT-HALL", "supply_pressure_sensor_id": "PT-HALL-S", "return_pressure_sensor_id": "PT-HALL-R", "supply_temp_sensor_id": "TT-HALL-S", "return_temp_sensor_id": "TT-HALL-R", "remarks": "公共大厅支路"},
        "CHW-MAIN-01": {"zone_id": "Z-A00", "room_id": "-", "pipe_level": "main", "pipe_type": "supply", "pipe_dn": "DN300", "pipe_length_m": 160, "design_flow_m3h": 900, "design_velocity_ms": 2.0, "supply_temp_c": 7, "return_temp_c": 12, "terminal_dp_kpa": 0, "friction_coeff": 0.08, "local_loss_coeff": 8.0, "valve_id": "-", "flow_meter_id": "FT-MAIN", "supply_pressure_sensor_id": "PT-MAIN-S", "return_pressure_sensor_id": "PT-MAIN-R", "supply_temp_sensor_id": "TT-MAIN-S", "return_temp_sensor_id": "TT-MAIN-R", "remarks": "冷冻水供水干管"}
    },
    "air_branches": {
        "AIR-A301-S": {"zone_id": "Z-A02", "room_id": "R-A301", "duct_level": "terminal", "duct_type": "supply", "duct_area_m2": 0.32, "duct_length_m": 24, "design_airflow_m3h": 2500, "design_air_velocity_ms": 2.17, "supply_air_temp_c": 14, "return_air_temp_c": 26, "air_resistance_coeff": 0.9, "local_loss_coeff": 30, "damper_id": "DMP-A301", "airflow_sensor_id": "AF-A301", "air_velocity_sensor_id": "AV-A301", "air_pressure_sensor_id": "DP-A301", "supply_air_temp_sensor_id": "SAT-A301", "return_air_temp_sensor_id": "RAT-A301", "fan_id": "FAN-AHU-01", "remarks": "301房间送风支管"},
        "AIR-HALL-S": {"zone_id": "Z-A01", "room_id": "R-HALL01", "duct_level": "branch", "duct_type": "supply", "duct_area_m2": 1.5, "duct_length_m": 40, "design_airflow_m3h": 60000, "design_air_velocity_ms": 11.1, "supply_air_temp_c": 14, "return_air_temp_c": 26, "air_resistance_coeff": 0.9, "local_loss_coeff": 30, "damper_id": "DMP-HALL", "airflow_sensor_id": "AF-HALL", "air_velocity_sensor_id": "AV-HALL", "air_pressure_sensor_id": "DP-HALL", "supply_air_temp_sensor_id": "SAT-HALL", "return_air_temp_sensor_id": "RAT-HALL", "fan_id": "FAN-AHU-HALL", "remarks": "大厅送风支管"},
        "AIR-MAIN-S": {"zone_id": "Z-A00", "room_id": "-", "duct_level": "main", "duct_type": "supply", "duct_area_m2": 3.0, "duct_length_m": 80, "design_airflow_m3h": 120000, "design_air_velocity_ms": 11.1, "supply_air_temp_c": 14, "return_air_temp_c": 26, "air_resistance_coeff": 0.8, "local_loss_coeff": 40, "damper_id": "-", "airflow_sensor_id": "AF-MAIN", "air_velocity_sensor_id": "AV-MAIN", "air_pressure_sensor_id": "DP-MAIN", "supply_air_temp_sensor_id": "SAT-MAIN", "return_air_temp_sensor_id": "RAT-MAIN", "fan_id": "FAN-AHU-01", "remarks": "送风干管"}
    },
    "cw_branches": {
        "CW-MAIN-01": {"serve_equipment_id": "CH-01", "pipe_level": "main", "pipe_type": "supply", "pipe_dn": "DN250", "pipe_length_m": 120, "design_flow_m3h": 850, "design_velocity_ms": 1.9, "cw_supply_temp_c": 32, "cw_return_temp_c": 37, "loop_dp_kpa": 120, "pump_id": "CWP-01", "cooling_tower_id": "CT-01", "flow_meter_id": "FT-CW-01", "supply_pressure_sensor_id": "PT-CW-S", "return_pressure_sensor_id": "PT-CW-R", "supply_temp_sensor_id": "TT-CW-S", "return_temp_sensor_id": "TT-CW-R", "remarks": "冷却水主回路"},
        "CW-BR-CH01": {"serve_equipment_id": "CH-01", "pipe_level": "branch", "pipe_type": "supply", "pipe_dn": "DN200", "pipe_length_m": 45, "design_flow_m3h": 280, "design_velocity_ms": 1.7, "cw_supply_temp_c": 32, "cw_return_temp_c": 37, "loop_dp_kpa": 90, "pump_id": "CWP-01", "cooling_tower_id": "CT-01", "flow_meter_id": "FT-CW-CH01", "supply_pressure_sensor_id": "PT-CW-CH01-S", "return_pressure_sensor_id": "PT-CW-CH01-R", "supply_temp_sensor_id": "TT-CW-CH01-S", "return_temp_sensor_id": "TT-CW-CH01-R", "remarks": "冷机1冷却水支路"}
    },
    "bas_points": {
        "FT-A301": {"point_name": "301房间冷冻水流量", "point_type": "AI", "system": "CHW", "linked_object_id": "CHW-BR-A301", "measured_variable": "流量", "unit": "m³/h", "range_min": 0, "range_max": 10, "alarm_low": 0.5, "alarm_high": 8, "sample_interval_s": 60, "participate_control": "是", "remarks": "用于支路冷量估算"},
        "PT-A301-S": {"point_name": "301房间供水压力", "point_type": "AI", "system": "CHW", "linked_object_id": "CHW-BR-A301", "measured_variable": "压力", "unit": "kPa", "range_min": 0, "range_max": 600, "alarm_low": 80, "alarm_high": 450, "sample_interval_s": 60, "participate_control": "是", "remarks": "判断支路阻力"},
        "AV-A301": {"point_name": "301房间送风风速", "point_type": "AI", "system": "AIR", "linked_object_id": "AIR-A301-S", "measured_variable": "风速", "unit": "m/s", "range_min": 0, "range_max": 15, "alarm_low": 0.5, "alarm_high": 8, "sample_interval_s": 60, "participate_control": "是", "remarks": "判断风管阻力和噪声"},
        "DMP-A301": {"point_name": "301房间风阀开度", "point_type": "AO", "system": "AIR", "linked_object_id": "AIR-A301-S", "measured_variable": "阀门开度", "unit": "%", "range_min": 0, "range_max": 100, "alarm_low": 0, "alarm_high": 100, "sample_interval_s": 60, "participate_control": "是", "remarks": "参与风量调节"},
        "FT-CW-01": {"point_name": "冷却水主回路流量", "point_type": "AI", "system": "CW", "linked_object_id": "CW-MAIN-01", "measured_variable": "流量", "unit": "m³/h", "range_min": 0, "range_max": 1200, "alarm_low": 100, "alarm_high": 1000, "sample_interval_s": 60, "participate_control": "是", "remarks": "影响冷凝侧换热与冷机COP"}
    }
}

MODE_LABELS: dict = {
    "LOW": "低负荷多联机模式",
    "MID": "中负荷水氟协同模式",
    "HIGH": "高负荷集中水系统模式",
    "急停断开": "急停断开",
}

DISPLAY_NAME_MAP: dict = {
    "BACnet_AV_9001_LockTimer": "模态防抖锁定计时器",
    "BACnet_DO_3001_Chiller_Units": "冷机投运台数指令",
    "BACnet_AO_4001_VRF_Demand_kW": "多联机需求冷量指令(kW)",
    "BACnet_BI_3002_Chiller_RunStatus": "冷机运行状态反馈",
    "BACnet_BI_4002_VRF_RunStatus": "多联机运行状态反馈",
    "Chiller_Actual_Power_kW": "冷机实际功率(kW)",
    "VRF_Actual_Power_kW": "多联机实际功率(kW)",
    "Chiller_Delivered_Cooling_kW": "冷机交付冷量(kW)",
    "VRF_Delivered_Cooling_kW": "多联机交付冷量(kW)",
}

__all__ = [
    "DEFAULT_SYS_CONFIG",
    "DEFAULT_BUILDING_CONFIGS",
    "DEFAULT_SCENARIOS",
    "DEFAULT_SEQUENCE_PLAN",
    "DEFAULT_POINT_LEDGER_TEMPLATE",
    "MODE_LABELS",
    "DISPLAY_NAME_MAP",
    "STRATEGY_REGISTRY",
]


# ---------------------------------------------------------------------------
# STRATEGY_REGISTRY (FEAT-004): the UI control-strategy combo reads this.
# Only LOCAL strategies are listed here; cloud / LLM-driven control strategies
# have been deleted. Reporting-only LLM providers live in
# ``data/configs/llm_providers.py`` under ``LLM_PROVIDER_PRESETS_FOR_REPORTING``
# and are NEVER consumed by the control loop.
# ---------------------------------------------------------------------------
STRATEGY_REGISTRY: dict = {
    "rule": {"label": "本地阈值规则控制", "type": "local"},
    "mpc": {"label": "本地多步预测控制(MPC)", "type": "local"},
}
