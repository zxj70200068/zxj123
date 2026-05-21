# LEGACY FROZEN COPY - retained for reference only. New code MUST NOT import from this file. See REFACTOR_NOTES.md.
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import json
import math
import os
import csv
import re
import threading
import queue
import traceback
import urllib.request
import urllib.error
import datetime
import shutil
import random
import time
try:
    import psutil as _psutil          # 可选依赖：边缘性能监控
    _PSUTIL_OK = True
except ImportError:
    _psutil = None
    _PSUTIL_OK = False
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import minimize, Bounds as SpBounds
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib
import matplotlib.font_manager

# =====================================================================
# 字体安全防线：跨平台动态检测系统可用中文字体
# =====================================================================
try:
    system_fonts = [f.name for f in matplotlib.font_manager.fontManager.ttflist]
    font_preferences = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Arial Unicode MS', 'Heiti TC', 'STHeiti']
    matched_font = "sans-serif"
    for font in font_preferences:
        if font in system_fonts:
            matched_font = font
            break
    matplotlib.rcParams['font.sans-serif'] = [matched_font] + matplotlib.rcParams['font.sans-serif']
except Exception:
    matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

# =====================================================================
# 0. 全局配置区与策略注册表
# =====================================================================
CONFIG_API_PATH = "config_api.json"
APP_ERROR_LOG = "app_error.log"

def log_error(context, err):
    """写入本地错误日志，便于 exe 现场排查；日志失败不影响主程序。"""
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(APP_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{context}] {type(err).__name__}: {err}\n")
            tb = traceback.format_exc()
            if tb and "NoneType: None" not in tb:
                f.write(tb + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
# 系统级默认参数（DEFAULT_SYS_CONFIG）说明
# ─────────────────────────────────────────────────────────────────────
# 注：DEFAULT_SYS_CONFIG 以 JSON 三引号字符串持久化，由 json.loads 反序列化为 sys_config，
#   JSON 规范不允许在字符串内嵌行内注释，故关键字段语义统一在此处集中说明：
#
# rc_model_params（一阶 RC 建筑热模型参数）
#   - heat_gain_coeff = 0.001 ：热容倒数 1/C_building [kW⁻¹·hr⁻¹]，
#     与建筑热时间常数 tau ≈ 25 min 同源，标定室温对负荷扰动的瞬态响应斜率。
#   - envelope_ua_coeff = 0.015 ：围护结构 UA/C 比值 [hr⁻¹]，
#     反映围护热损与室内热容的比例，决定室温向室外干球温度漂移的衰减速率。
#
# tou_price（分时电价，福建省电网夏季峰平谷参考）
#   - peak_price = 1.20 元/kWh ：峰段电价（夏季尖峰）
#   - flat_price = 0.80 元/kWh ：平段电价
#   - valley_price = 0.35 元/kWh ：谷段电价（夜间低谷）
#   - peak_hours = [9, 10, 11, 14, 15, 16, 17, 18] ：峰段时段（9-12 时、14-19 时）
#   - valley_hours = [23, 0, 1, 2, 3, 4, 5, 6] ：谷段时段（23 时至次日 7 时）
#   未列入 peak_hours / valley_hours 的小时按 flat_price 计费。
DEFAULT_SYS_CONFIG = """
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

DEFAULT_BUILDING_CONFIGS = {
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

DEFAULT_SCENARIOS = {
    "01_上午运行高峰": {"t_out": 33.5, "r_zones": {"公共大厅": 0.85, "标准功能区": 1.0, "高人员密度区": 0.75, "设备机房": 0.6}, "c_sch": 1.0, "c_occ": 0.92, "is_night": False},
    "02_午间低谷": {"t_out": 36.5, "r_zones": {"公共大厅": 0.45, "标准功能区": 0.35, "高人员密度区": 0.55, "设备机房": 0.65}, "c_sch": 0.55, "c_occ": 0.60, "is_night": False},
    "03_下午高峰": {"t_out": 38.8, "r_zones": {"公共大厅": 0.9, "标准功能区": 0.85, "高人员密度区": 1.0, "设备机房": 0.7}, "c_sch": 0.95, "c_occ": 0.88, "is_night": False},
    "04_晚间局部运行": {"t_out": 30.0, "r_zones": {"公共大厅": 0.35, "标准功能区": 0.45, "高人员密度区": 0.2, "设备机房": 0.7}, "c_sch": 0.65, "c_occ": 0.55, "is_night": False},
    "05_夜间值班": {"t_out": 26.5, "r_zones": {"公共大厅": 0.05, "标准功能区": 0.05, "高人员密度区": 0.0, "设备机房": 1.0}, "c_sch": 0.1, "c_occ": 0.05, "is_night": True}
}

DEFAULT_SEQUENCE_PLAN = [
    {"scenario": "05_夜间值班", "steps": 24},
    {"scenario": "01_上午运行高峰", "steps": 16},
    {"scenario": "02_午间低谷", "steps": 12},
    {"scenario": "03_下午高峰", "steps": 24},
    {"scenario": "04_晚间局部运行", "steps": 20}
]

DEFAULT_POINT_LEDGER_TEMPLATE = {
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


PROVIDER_PRESETS = {
    "qwen": {"display_name": "千问 / 阿里云百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "api_key_env": "DASHSCOPE_API_KEY"},
    "deepseek": {"display_name": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "api_key_env": "DEEPSEEK_API_KEY"},
    "doubao": {"display_name": "豆包 / 火山方舟", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-seed-1-6", "api_key_env": "ARK_API_KEY"},
    "hunyuan": {"display_name": "腾讯混元 / 元宝预留", "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "model": "hunyuan-standard", "api_key_env": "HUNYUAN_API_KEY"},
    "custom": {"display_name": "自定义OpenAI兼容接口", "base_url": "", "model": "", "api_key_env": ""}
}

STRATEGY_REGISTRY = {
    "规则控制(本地)": {"type": "local", "provider": "local_rule", "desc": "本地阈值规则控制"},
    "预测寻优(本地MPC)": {"type": "local", "provider": "local_mpc", "desc": "本地模型预测控制"},
    "BiLSTM 云端预测(校园专网)": {"type": "cloud", "provider": "bilstm", "desc": "校园云端 BiLSTM t+1 冷负荷预测 + 推荐策略"},
    "千问 / 阿里云百炼": {"type": "cloud", "provider": "qwen", "desc": "阿里云百炼 OpenAI 兼容接口"},
    "DeepSeek": {"type": "cloud", "provider": "deepseek", "desc": "DeepSeek OpenAI 兼容接口"},
    "豆包 / 火山方舟": {"type": "cloud", "provider": "doubao", "desc": "火山方舟 OpenAI 兼容接口"},
    "腾讯混元 / 元宝预留": {"type": "cloud", "provider": "hunyuan", "desc": "腾讯系模型接口预留"},
    "自定义OpenAI兼容接口": {"type": "cloud", "provider": "custom", "desc": "用户自定义 OpenAI 兼容接口"}
}

MODE_LABELS = {
    "LOW": "低负荷多联机模式",
    "MID": "中负荷水氟协同模式",
    "HIGH": "高负荷集中水系统模式",
    "急停断开": "急停断开"
}

DISPLAY_NAME_MAP = {
    "BACnet_AV_9001_LockTimer": "模态防抖锁定计时器",
    "BACnet_DO_3001_Chiller_Units": "冷机投运台数指令",
    "BACnet_AO_4001_VRF_Demand_kW": "多联机需求冷量指令(kW)",
    "BACnet_BI_3002_Chiller_RunStatus": "冷机运行状态反馈",
    "BACnet_BI_4002_VRF_RunStatus": "多联机运行状态反馈",
    "Chiller_Actual_Power_kW": "冷机实际功率(kW)",
    "VRF_Actual_Power_kW": "多联机实际功率(kW)",
    "Chiller_Delivered_Cooling_kW": "冷机交付冷量(kW)",
    "VRF_Delivered_Cooling_kW": "多联机交付冷量(kW)"
}

PROV_NAME_TO_KEY = {v["display_name"]: k for k, v in PROVIDER_PRESETS.items()}

# =====================================================================
# 1. 历史运行数据记录模块
# =====================================================================
class HistoryLogger:
    """实时运行状态快照记录器：本地边缘侧沉淀 40 维多维特征数据集（含 schema_version 数据格式版本字段，
    覆盖时序、温度、水力、寻优策略、安全超驰）

    工程定位
    --------
    每一仿真步长落盘一行 40 维特征，作为冷热源-多联机群控的边缘侧时序档案。
    数据按下列五大特征族组织，覆盖白箱物理仿真与上层调度决策的全链路证据：
        1) 时序与电价：timestamp / sim_time_min / hour / electricity_price / c_sch / c_occ / is_night
        2) 室内外热环境：t_out / t_in / load_kw / delivered_kw / cooling_satisfaction / r_zones_json
        3) 寻优策略与执行：current_mode_before / mode / ai_requested_mode / strategy_type
        4) 设备能耗与机组群控：opt_power_kw / traditional_power_kw / saving_rate / step_kwh /
           step_cost_yuan / chiller_units / chiller_plr_percent / chiller_cop / chiller_power_kw /
           vrf_power_kw / pump_power_kw / transformer_load_percent
        5) 水力与安全：chilled_water_flow_m3h / pump_head_kpa / pump_freq_hz / alarms /
           safety_override / lcc_kwh_saved / lcc_cost_saved
    每行首列 schema_version 标注本数据格式的版本号（当前 "1.0"），用于下游 BiLSTM
    训练管线在 schema 演进时的向前/向后兼容判定。

    云端 BiLSTM 协同
    --------------
    本地沉淀的 40 维数据集定期回流至校园专网云端，作为 BiLSTM 模型的离线训练与微调样本，
    支撑 t+1 冷负荷预测与调度策略的持续闭环优化；当云端推理通道异常时，本地策略
    （MPCStrategy/RuleBasedStrategy）按既有降级逻辑接管，CSV 写盘流程保持不变。
    每行对应一个仿真步长，列数与列序固定，确保下游训练管线零侵入消费。

    schema 演进记录
    --------------
    v1.0 ：原 40 列。
    v1.1 ：在 v1.0 末尾追加 12 列物理过程量（PhysicsSimulationEngine.simulate_all 输出）：
           solar_irradiance_wm2 / worst_loop_dp_kpa / vav_opening_avg_pct / vav_openings_json /
           exv_opening_pct / duct_static_pressure_pa / fan_freq_hz / total_air_flow_m3h /
           disturbance_load_kw / evap_temp_c / refrigerant_mass_flow_kgh / chw_supply_temp_c。
           前 40 列的列名与列序与 v1.0 完全一致，下游按列序读前 40 列保持向后兼容；
           读取 v1.1 数据时，老 v1.0 的 CSV 会被自动备份为 <原名>.v10.bak，新文件按 v1.1 写入。
    """
    def __init__(self, file_path="history_log.csv"):
        self.file_path = file_path
        # 注意：headers 与 row 必须字段数量完全一致，共 40 列（首列为 schema_version）；
        # 严禁在此处增删列，任何特征扩展须同步更新下游 BiLSTM 训练脚本与 schema 校验。
        self.headers = [
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
            # ── v1.1 新增：物理过程量（PhysicsSimulationEngine.simulate_all 输出） ──
            "solar_irradiance_wm2",        # Solar_Rad
            "worst_loop_dp_kpa",           # Loop_DP
            "vav_opening_avg_pct",         # VAV_Opening 平均
            "vav_openings_json",           # VAV_Opening 各区明细（JSON 字符串）
            "exv_opening_pct",             # EXV_Opening
            "duct_static_pressure_pa",     # 主风管余压
            "fan_freq_hz",                 # 风机频率
            "total_air_flow_m3h",          # 总送风量
            "disturbance_load_kw",         # 环境扰动等效冷负荷
            "evap_temp_c",                 # 蒸发温度
            "refrigerant_mass_flow_kgh",   # 制冷剂质量流量
            "chw_supply_temp_c",           # 冷冻水供水温度（与 hyd 不同源，物理引擎反算）
        ]
        # 文件不存在 → 直接写新表头
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(self.headers)
            except Exception:
                pass
        else:
            # 文件已存在 → 检查首行列数；若小于当前 headers 长度，
            # 视为旧 schema (v1.0)，将旧文件改名备份，再写入新表头。
            try:
                with open(self.file_path, "r", encoding="utf-8-sig") as f:
                    first = f.readline()
                old_cols = first.count(",") + 1 if first else 0
                if 0 < old_cols < len(self.headers):
                    backup_path = self.file_path + ".v10.bak"
                    try:
                        if os.path.exists(backup_path):
                            os.remove(backup_path)
                    except Exception:
                        pass
                    try:
                        os.rename(self.file_path, backup_path)
                    except Exception:
                        pass
                    with open(self.file_path, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.writer(f)
                        writer.writerow(self.headers)
            except Exception:
                pass

    def log_step(self, building_name, scenario_name, res, factor=None, engine=None, run_type="single_step"):
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sys_cfg = res.get("sys_safety_cfg", {})
            trans_limit = sys_cfg.get('transformer_capacity_kva', 2500) * sys_cfg.get('power_factor', 0.9)
            opt_p = res.get('opt_p', 0.0)
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

            # v1.1 新增：从 res 中提取物理过程量（PhysicsSimulationEngine 反算结果）
            physics = res.get("physics_state") or {}
            if not isinstance(physics, dict):
                physics = {}
            vav_dict = physics.get("vav_openings_pct") or {}
            if isinstance(vav_dict, dict) and vav_dict:
                try:
                    vav_avg_pct = round(sum(float(v) for v in vav_dict.values()) / len(vav_dict), 2)
                except Exception:
                    vav_avg_pct = ""
                try:
                    vav_openings_json = json.dumps(vav_dict, ensure_ascii=False)
                except Exception:
                    vav_openings_json = "{}"
            else:
                vav_avg_pct = ""
                vav_openings_json = "{}"

            # 严格按 headers 顺序构建 row，共 40 列（首列 schema_version 标注数据格式版本）
            row = [
                "1.1",                                                       # schema_version
                ts,                                                          # timestamp
                building_name,                                               # building_name
                scenario_name,                                               # scenario_name
                run_type,                                                    # run_type
                res.get("time", 0),                                          # sim_time_min
                hour,                                                        # hour
                electricity_price,                                           # electricity_price
                c_sch,                                                       # c_sch
                c_occ,                                                       # c_occ
                is_night,                                                    # is_night
                r_zones_json,                                                # r_zones_json
                res.get("t_out", 0),                                         # t_out
                res.get("t_in", 0),                                          # t_in
                res.get("load", 0),                                          # load_kw
                res.get("delivered", 0),                                     # delivered_kw
                res.get("cooling_satisfaction_val", 0),                      # cooling_satisfaction
                current_mode_before,                                         # current_mode_before
                res.get("combo", ""),                                        # mode
                res.get("ai_requested_mode", ""),                            # ai_requested_mode
                res.get("ai_suggested_type", ""),                            # strategy_type
                opt_p,                                                       # opt_power_kw
                res.get("trad_p", 0),                                        # traditional_power_kw
                res.get("rate", 0),                                          # saving_rate
                step_kwh,                                                    # step_kwh
                step_cost_yuan,                                              # step_cost_yuan
                chiller_status.get("running_units", 0),                     # chiller_units
                chiller_status.get("plr_percent", 0),                        # chiller_plr_percent
                chiller_status.get("cop", 0),                                # chiller_cop
                res.get("cmd", {}).get("Chiller_Actual_Power_kW", 0),        # chiller_power_kw
                res.get("cmd", {}).get("VRF_Actual_Power_kW", 0),            # vrf_power_kw
                hyd.get("pump_power_kw", 0),                                 # pump_power_kw
                hyd.get("total_flow_m3h", 0),                                # chilled_water_flow_m3h
                hyd.get("pump_head_kpa", 0),                                 # pump_head_kpa
                hyd.get("pump_freq_hz", 0),                                  # pump_freq_hz
                trans_load,                                                  # transformer_load_percent
                " | ".join(res.get("cmd", {}).get("alarms", [])),            # alarms
                res.get("safety_override", False),                           # safety_override
                res.get("total_kwh_saved", 0),                               # lcc_kwh_saved
                res.get("total_cost_saved", 0),                              # lcc_cost_saved
                # ── v1.1 物理过程量（来自 res["physics_state"] 扁平字典）──
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
        except Exception as e:
            log_error("HistoryLogger.log_step", e)

# =====================================================================
# 2. 配置管理与边界校验
# =====================================================================
class ConfigManager:
    def __init__(self):
        self.sys_config = json.loads(DEFAULT_SYS_CONFIG)
        self.scenarios = DEFAULT_SCENARIOS.copy()
        self.building_configs = DEFAULT_BUILDING_CONFIGS.copy()
        self.sequence_plan = DEFAULT_SEQUENCE_PLAN.copy()
        self.point_ledger = json.loads(json.dumps(DEFAULT_POINT_LEDGER_TEMPLATE, ensure_ascii=False))
        self.api_config = self._init_api_config()

    def _init_api_config(self):
        default_config = {"active_provider": "local_mpc", "providers": {}}
        for k, v in PROVIDER_PRESETS.items():
            default_config["providers"][k] = {
                "base_url": v["base_url"],
                "model": v["model"],
                "api_key": os.environ.get(v["api_key_env"], "") if v["api_key_env"] else ""
            }
        if not os.path.exists(CONFIG_API_PATH):
            try:
                with open(CONFIG_API_PATH, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
            return default_config
        else:
            try:
                with open(CONFIG_API_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "providers" not in data:
                    data["providers"] = {}
                for k, v in default_config["providers"].items():
                    if k not in data["providers"]:
                        data["providers"][k] = v
                return data
            except Exception:
                return default_config

    def save_api_config(self, provider_key, base_url, model, api_key):
        if "providers" not in self.api_config:
            self.api_config["providers"] = {}
        self.api_config["providers"][provider_key] = {"base_url": base_url, "model": model, "api_key": api_key}
        try:
            with open(CONFIG_API_PATH, "w", encoding="utf-8") as f:
                json.dump(self.api_config, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def get_provider_config(self, provider_key):
        return self.api_config.get("providers", {}).get(provider_key, {})

    def validate_building_config(self, data):
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

    def validate_scenarios(self, data):
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

    def validate_sequence_plan(self, data):
        if not isinstance(data, list):
            return False, "时序计划格式错误，必须为数组"
        for idx, item in enumerate(data):
            if "scenario" not in item or "steps" not in item:
                return False, f"时序计划第 {idx+1} 项缺少 scenario 或 steps"
            if not isinstance(item["steps"], int) or item["steps"] <= 0:
                return False, f"时序计划第 {idx+1} 项 steps 必须为正整数"
            if item["scenario"] not in self.scenarios:
                return False, f"时序计划引用了不存在的工况【{item['scenario']}】"
        return True, ""

    def load_external_config(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_keys = []
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
            log_error("ConfigManager.load_external_config", e)
            return False, f"导入配置失败: {e}", []

    def load_external_scenarios(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok, msg = self.validate_scenarios(data)
            if not ok:
                return False, msg
            self.scenarios = data
            return True, "环境工况导入成功"
        except Exception as e:
            log_error("ConfigManager.load_external_scenarios", e)
            return False, f"导入工况失败: {e}"

    def load_external_sequence(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok, msg = self.validate_sequence_plan(data)
            if not ok:
                return False, msg
            self.sequence_plan = data
            return True, "时序计划导入成功"
        except Exception as e:
            log_error("ConfigManager.load_external_sequence", e)
            return False, f"时序计划导入失败: {e}"


    def validate_point_ledger(self, data):
        """校验机电台账：引用关系、重复点位、正数边界与可降级警告。"""
        if not isinstance(data, dict):
            return False, "测点台账格式错误，必须为字典结构"
        required_sections = ["building_profile", "zones", "rooms", "chw_branches", "air_branches", "cw_branches", "bas_points"]
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

        def check_branch_room(section_name, branches):
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
                log_error("validate_point_ledger", ValueError(f"冷冻水管路 {bid} 未知管径 {br.get('pipe_dn')}，运行时将按 DN100 处理"))
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
                log_error("validate_point_ledger", ValueError(f"冷却水管路 {bid} 未知管径 {br.get('pipe_dn')}，运行时将按 DN200 处理"))
            if float(br.get("pipe_length_m", 0)) < 0:
                return False, f"冷却水管路 {bid} pipe_length_m 不得为负"
            if float(br.get("design_flow_m3h", 0)) < 0:
                return False, f"冷却水管路 {bid} design_flow_m3h 不得为负"
            if float(br.get("loop_dp_kpa", 0)) < 0:
                return False, f"冷却水管路 {bid} loop_dp_kpa 不得为负"

        seen_points = set()
        valid_objects = set(rooms.keys()) | set(chw.keys()) | set(air.keys()) | set(cw.keys()) | set(zones.keys())
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

    def load_external_point_ledger(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok, msg = self.validate_point_ledger(data)
            if not ok:
                return False, msg
            self.point_ledger = data
            return True, "机电测点台账导入成功"
        except Exception as e:
            log_error("ConfigManager.load_external_point_ledger", e)
            return False, f"导入测点台账失败: {e}"

    def export_point_ledger_template(self, file_path):
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_POINT_LEDGER_TEMPLATE, f, indent=2, ensure_ascii=False)
            return True, "通用建筑机电测点台账模板已导出"
        except Exception as e:
            log_error("ConfigManager.export_point_ledger_template", e)
            return False, f"导出模板失败: {e}"

    def export_point_ledger_csv_templates(self, folder_path):
        """将台账模板拆分为多个 CSV，便于 CAD/点表人员人工填写。"""
        try:
            os.makedirs(folder_path, exist_ok=True)
            section_to_file = {
                "zones": "zones.csv",
                "rooms": "rooms.csv",
                "chw_branches": "chw_branches.csv",
                "air_branches": "air_branches.csv",
                "cw_branches": "cw_branches.csv",
                "bas_points": "bas_points.csv"
            }
            for section, filename in section_to_file.items():
                data = DEFAULT_POINT_LEDGER_TEMPLATE.get(section, {})
                keys = set()
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
            log_error("ConfigManager.export_point_ledger_csv_templates", e)
            return False, f"导出CSV模板失败: {e}"

# =====================================================================
# 3. 冷冻水管网流体动力学数字孪生层
# =====================================================================
class HydraulicNetworkModel:
    def __init__(self, zone_specs, sys_config):
        self.zone_specs = zone_specs
        self.sys_config = sys_config
        self.dn_sizes = {
            "DN200": 0.20, "DN150": 0.15, "DN125": 0.125,
            "DN100": 0.10, "DN80": 0.08, "DN65": 0.065, "DN50": 0.05
        }
        total_design = sum(spec.get("design_load_kw", 1000.0) for spec in self.zone_specs.values())
        self.design_flow_m3h = max(1.0, total_design / (1.163 * 5.0))

    def calculate(self, cooling_distribution, supply_temp_c=7.0, return_temp_c=12.0):
        delta_t_c = max(1.0, return_temp_c - supply_temp_c)
        total_flow_m3h = 0.0
        branches_data = []
        branch_dps = []
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

                valve_opening = min(100.0, max(15.0, (cooling_kw / design_kw) * 100.0)) if design_kw > 0 else 15.0
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
                "return_air_temp": 26.0 if cooling_kw > 0 else "--"
            })

        # 安全：空列表时不调用 max
        empty_checkpoints = {
            "chiller_out": {"T": supply_temp_c, "P": 0.0, "F": 0.0},
            "pump_out": {"T": supply_temp_c, "P": 0.0, "F": 0.0},
            "distributor": {"T": supply_temp_c, "P": 0.0, "F": 0.0},
            "term_in": {"T": supply_temp_c, "P": 0.0, "F": "--"},
            "term_out": {"T": return_temp_c, "P": 0.0, "F": "--"},
            "return_main": {"T": return_temp_c, "P": 0.0, "F": 0.0}
        }

        if is_active and branch_dps:
            RESERVED_PRESSURE_KPA = 20.0  # 分水器至最不利末端资用压差预留值
            pump_head_kpa = max(branch_dps) + RESERVED_PRESSURE_KPA
            pump_head_m = pump_head_kpa / 9.81
            pump_efficiency = 0.72
            pump_power_kw = (total_flow_m3h * pump_head_m / (367.0 * pump_efficiency)) if pump_head_m > 0 else 0.0
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
                "return_main": {"T": return_temp_c, "P": round(p_return, 1), "F": round(total_flow_m3h, 2)}
            }
        else:
            pump_head_kpa = pump_head_m = pump_power_kw = pump_freq_hz = 0.0
            pump_speed_rpm = 0
            pump_vfd_percent = 0.0
            checkpoints = empty_checkpoints

        # ── 并联支路水力平衡检查：识别压差跨度过大的失调风险 ───────────
        # 仅在系统激活且存在多于一条带流量的支路时校核；阈值 15 kPa 为工程经验值，
        # 超过该跨度通常意味着平衡阀整定欠佳或最不利支路过远，需运维介入复核。
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
                        "supply_air_temp": "--", "return_air_temp": "--"
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
            "is_sleep": not is_active
        }


# =====================================================================
# 3.1 末端测点联动分析模型
# =====================================================================
class TerminalPointLinkageModel:
    """房间/区域末端测点联动仿真：支持区域级参数和房间/支路/点位台账参数。"""
    def __init__(self, zone_specs, sys_config, last_res=None, point_ledger=None):
        self.zone_specs = zone_specs
        self.sys_config = sys_config
        self.last_res = last_res or {}
        self.point_ledger = point_ledger or {}
        self.dn_sizes = {
            "DN300": 0.30, "DN250": 0.25, "DN200": 0.20, "DN150": 0.15, "DN125": 0.125,
            "DN100": 0.10, "DN80": 0.08, "DN65": 0.065, "DN50": 0.05, "DN40": 0.04, "DN32": 0.032
        }

    def _to_float(self, value, default):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def _current_zone_cooling_kw(self, zone_name, default_kw):
        hyd = self.last_res.get("hydraulic", {}) if isinstance(self.last_res, dict) else {}
        for b in hyd.get("branches", []):
            if b.get("zone_name") == zone_name and b.get("cooling_kw", 0) > 0:
                return float(b.get("cooling_kw", default_kw))
        return default_kw

    def available_targets(self):
        items = list(self.zone_specs.keys())
        for rid, room in self.point_ledger.get("rooms", {}).items():
            label = f"{rid} | {room.get('room_name', rid)}"
            if label not in items:
                items.append(label)
        return items

    def _resolve_target(self, target_name):
        rooms = self.point_ledger.get("rooms", {})
        zones = self.point_ledger.get("zones", {})
        room_id, room_cfg = None, None
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
                self.zone_specs.setdefault(zone_name, {
                    "area_type": z_ledger.get("area_type", "公共"),
                    "system_type": z_ledger.get("system_type", room_cfg.get("serve_system", "CHW")),
                    "design_load_kw": float(room_cfg.get("design_load_kw", z_ledger.get("design_load_kw", 1000))),
                    "terminal_type": room_cfg.get("terminal_type", z_ledger.get("terminal_type", "末端设备")),
                    "pipe_dn": "DN100", "pipe_length_m": 100.0, "terminal_dp_kpa": 35.0,
                    "air_duct_area_m2": 1.2,
                    "air_duct_length_m": 35.0,
                    "air_resistance_coeff": 0.9,
                    "fan_efficiency": 0.60,
                    "design_airflow_m3h": float(zv) * 250.0
                })
            return zone_name, room_id, room_cfg
        return target_name, None, None

    def _find_branch(self, section, room_id=None, zone_name=None):
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

    def _linked_points(self, object_id):
        pts = []
        for pid, p in self.point_ledger.get("bas_points", {}).items():
            if p.get("linked_object_id") == object_id:
                pts.append((pid, p))
        return pts

    def analyze_zone(self, zone_name, overrides=None):
        overrides = overrides or {}
        resolved_zone, room_id, room_cfg = self._resolve_target(zone_name)
        z_cfg = dict(self.zone_specs.get(resolved_zone, {}))
        if room_cfg:
            z_cfg["design_load_kw"] = float(room_cfg.get("design_load_kw", z_cfg.get("design_load_kw", 1000.0)))
            z_cfg["terminal_type"] = room_cfg.get("terminal_type", z_cfg.get("terminal_type", "末端设备"))
            z_cfg["design_airflow_m3h"] = float(room_cfg.get("design_airflow_m3h", z_cfg.get("design_airflow_m3h", z_cfg.get("design_load_kw", 1000.0) * 250.0)))
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
            z_cfg["air_resistance_coeff"] = float(air_branch.get("air_resistance_coeff", z_cfg.get("air_resistance_coeff", 0.9)))
            z_cfg["design_airflow_m3h"] = float(air_branch.get("design_airflow_m3h", z_cfg.get("design_airflow_m3h", z_cfg.get("design_load_kw", 1000.0) * 250.0)))

        design_kw = float(z_cfg.get("design_load_kw", 1000.0))
        terminal_type = z_cfg.get("terminal_type", "末端设备")
        dn = z_cfg.get("pipe_dn", "DN100")
        diameter_m = self.dn_sizes.get(dn, 0.10)
        pipe_length_m = float(z_cfg.get("pipe_length_m", 100.0))
        terminal_dp_kpa = float(z_cfg.get("terminal_dp_kpa", 35.0))
        cooling_kw_default = self._current_zone_cooling_kw(resolved_zone, design_kw * 0.7)

        rows = []
        def add(category, name, value, unit, note):
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
        flow_default = default_branch_flow if default_branch_flow > 0 else (cooling_kw_default / (1.163 * chw_delta_t) if chw_delta_t > 0 else 0.0)
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
        valve_opening = min(100.0, max(0.0, (chw_cooling_kw / design_kw) * 100.0)) if design_kw > 0 else 0.0
        pump_power_kw = chw_flow_m3h * (branch_dp_kpa / 9.81) / (367.0 * 0.72) if branch_dp_kpa > 0 else 0.0
        chiller_power_delta = chw_cooling_kw / 5.5 if chw_cooling_kw > 0 else 0.0

        add("冷冻水管", "区域/末端类型", f"{resolved_zone} / {terminal_type}", "-", "当前选择的区域、房间或末端形式")
        add("冷冻水管", "供水温度", float(chw_branch.get("supply_temp_c", 7.0)) if chw_branch else 7.0, "℃", "冷冻水供水侧温度表")
        add("冷冻水管", "回水温度", float(chw_branch.get("return_temp_c", 12.0)) if chw_branch else 12.0, "℃", "冷冻水回水侧温度表")
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
        fan_power_kw = airflow_m3s * total_air_dp / fan_eff / 1000.0 if fan_eff > 0 else 0.0
        supply_air_temp = float(air_branch.get("supply_air_temp_c", room_cfg.get("supply_air_temp_c", 14.0) if room_cfg else 14.0)) if air_branch else 14.0
        return_air_temp = float(air_branch.get("return_air_temp_c", room_cfg.get("return_air_temp_c", 26.0) if room_cfg else 26.0)) if air_branch else 26.0
        # 风侧显热冷量：Q = ρ·cp·V·ΔT / 1000
        # 其中 ρ·cp/1000 ≈ 1.2 kg/m³ × 1.005 kJ/(kg·K) / 1000 ≈ 0.0012 kW·s/(m³·K)
        # 简化为 1.2 是工程常用近似（隐含单位换算，airflow_m3s 的量纲已含 m³/s）
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
        cw_supply_temp = self._to_float(overrides.get("cooling_water_supply_temp"), float(cw_branch.get("cw_supply_temp_c", 32.0)) if cw_branch else 32.0)
        cw_return_temp = self._to_float(overrides.get("cooling_water_return_temp"), float(cw_branch.get("cw_return_temp_c", 37.0)) if cw_branch else 37.0)
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
        cw_pump_power_kw = cw_flow_m3h * (condenser_loop_dp_kpa / 9.81) / (367.0 * 0.70) if cw_flow_m3h > 0 else 0.0
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
                add("BAS/DDC点位", point.get("point_name", pid), pid, point.get("unit", "-"), f"{point.get('system','-')} | {point.get('measured_variable','-')} | 参与控制:{point.get('participate_control','否')}")

        return rows


# =====================================================================
# 3.2 过程导向白盒物理仿真引擎
# =====================================================================
class PhysicsSimulationEngine:
    """过程导向白盒物理仿真引擎（独立类，不接入主循环）。

    设计目标：
        将原有"黑盒结果"型输出（仅整体能耗与 COP）扩展为"过程导向"白盒视图，
        逐环节展示水侧/风侧/多联机/外扰的中间物理量，便于答辩可视化与机理排障。

    覆盖范围：
        1. 水侧（CHW Loop）  ：基于 Q = c·m·ΔT 与水泵相似律反算流量、压降、阀位、频率、扬程。
        2. 风侧（VAV）        ：基于 Q = ρ·cp·V·ΔT 反算各区送风量与 VAV 开度，主风管余压控制、风机相似律。
        3. 多联机（VRF）      ：基于 R410A 气液两相焓差反算制冷剂质量流量，EXV 开度与 PLR 联动。
        4. 环境扰动           ：以太阳常数 1353 W/m² 为基准，结合大气透射率、太阳高度角、围护结构得热系数估算等效冷负荷。

    所有方法返回 dict（键名带物理量单位后缀），可直接馈入 UI/日志/报表层。
    """

    # ───────────────────── 物性与工程基准常量 ─────────────────────
    SOLAR_CONSTANT = 1353.0          # 太阳常数（W/m²，硬性基准，按用户要求）
    CP_WATER_KJ = 4.187              # 水比热容 kJ/(kg·K)
    RHO_WATER = 1000.0               # 水密度 kg/m³（7~12℃ 工况近似）
    RHO_CP_AIR = 1.2                 # 干空气 ρ·cp 工程近似 kJ/(m³·K)
    DELTA_T_AIR_K = 10.0             # 送风温差工程取值 K（7℃ 冷冻水 / 16℃ 送风 / 26℃ 室温）
    R410A_LATENT_KJ = 190.0          # R410A 蒸发器进出口焓差工程近似 kJ/kg（180~200 kJ/kg 区间）

    # 水力网络
    RATED_COOLING_LOAD_KW = 2400.0   # 额定冷负荷 kW（100% PLR 基准）
    RATED_LOOP_DP_KPA = 320.0        # 额定工况最不利环路压降 kPa（沿程 + 局部）
    PUMP_RATED_FREQ_HZ = 50.0        # 工频
    PUMP_MIN_FREQ_HZ = 20.0          # 变频水泵下限频率（防失速）
    GRAVITY = 9.81                   # 重力加速度 m/s²

    # 风侧
    RATED_AIR_FLOW_M3H = 60000.0     # 额定总送风量 m³/h（用于风机相似律基准）
    DUCT_STATIC_MIN_PA = 100.0       # 主风管余压工程下限 Pa
    DUCT_STATIC_MAX_PA = 300.0       # 主风管余压工程上限 Pa
    FAN_RATED_FREQ_HZ = 50.0
    FAN_MIN_FREQ_HZ = 20.0

    # 多联机 EXV
    EXV_BASE_OPENING_PCT = 25.0      # EXV 基础开度（保证最小过热度的开度截距）
    EXV_GAIN_PCT = 65.0              # EXV 随 PLR 的增益系数
    EXV_MIN_PCT = 10.0
    EXV_MAX_PCT = 95.0
    VRF_RATED_LOAD_KW = 360.0        # 多联机系统额定冷量 kW

    # 环境扰动
    ATMOS_TRANSMISSIVITY = 0.70      # 大气透射率（晴天典型 0.6~0.75）
    ENVELOPE_GAIN_COEFF = 0.55       # 围护结构 + 玻璃综合得热系数（含 SHGC 与遮阳）
    OPAQUE_U_W_M2K = 1.20            # 不透明围护传热系数 W/(m²·K)
    INDOOR_SET_TEMP_C = 26.0         # 室内设定温度
    SUNRISE_HOUR = 6.0
    SUNSET_HOUR = 18.0

    _EPS = 1e-6                      # 通用防零除阈值

    def __init__(self, rated_cooling_kw=None, rated_air_flow_m3h=None, vrf_rated_kw=None):
        """支持以构造参数覆写额定基准值，便于不同建筑规模复用。"""
        self.rated_cooling_kw = float(rated_cooling_kw) if rated_cooling_kw else self.RATED_COOLING_LOAD_KW
        self.rated_air_flow_m3h = float(rated_air_flow_m3h) if rated_air_flow_m3h else self.RATED_AIR_FLOW_M3H
        self.vrf_rated_kw = float(vrf_rated_kw) if vrf_rated_kw else self.VRF_RATED_LOAD_KW

    # ────────────────────────── 水侧 ──────────────────────────
    def calc_water_side(self, cooling_load, supply_temp):
        """冷冻水环路过程量反算。

        物理依据：
            1. 能量守恒 Q = c_p · m · ΔT  →  反算质量流量 m (kg/s)
               体积流量 V = m / ρ × 3600  → m³/h
               其中回水温度按工况经验取 supply_temp + 5℃，对应 ΔT = 5 K（一次冷冻水侧典型温差）。
            2. 水泵相似律 Q ∝ N，H ∝ N²  →  频率 f = 50 × (V/V额) 反算变频频率。
            3. 管网阻力相似 Δp ∝ V²    →  最不利环路压降按额定值与流量比平方缩放。
            4. 末端两通调节阀典型流量特性：开度 ≈ 0.3 + 0.7·PLR（部分负荷线性化近似）。
            5. 扬程 H(m) = Δp(kPa) × 1000 / (ρ·g) ≈ Δp(kPa) / 9.81（水柱换算）。

        参数：
            cooling_load (float): 当前冷负荷 kW
            supply_temp  (float): 冷冻水供水温度 ℃（典型 5~9℃）
        返回：
            dict — 含流量、压降、阀位、频率、扬程、PLR 等过程量。
        """
        try:
            load_kw = max(0.0, float(cooling_load))
            t_supply = float(supply_temp)
            t_return = t_supply + 5.0
            delta_t = max(self._EPS, t_return - t_supply)

            # 1) 质量流量与体积流量
            mass_flow_kgs = (load_kw * 1.0) / (self.CP_WATER_KJ * delta_t)
            flow_m3h = mass_flow_kgs * 3600.0 / max(self._EPS, self.RHO_WATER)

            # 2) 部分负荷率（PLR）
            plr = min(1.2, load_kw / max(self._EPS, self.rated_cooling_kw))

            # 3) 管网阻力相似律：Δp ∝ V²
            rated_flow_m3h = (self.rated_cooling_kw * 1.0) / (self.CP_WATER_KJ * 5.0) * 3600.0 / self.RHO_WATER
            flow_ratio = flow_m3h / max(self._EPS, rated_flow_m3h)
            worst_loop_dp_kpa = self.RATED_LOOP_DP_KPA * (flow_ratio ** 2)

            # 4) 末端二通阀平均开度（典型部分负荷阀位曲线）
            valve_open = 0.30 + 0.70 * min(1.0, max(0.0, plr))
            valve_open_pct = float(np.clip(valve_open * 100.0, 10.0, 100.0))

            # 5) 变频水泵频率（相似律：Q ∝ N）
            pump_freq_hz = float(np.clip(self.PUMP_RATED_FREQ_HZ * flow_ratio,
                                         self.PUMP_MIN_FREQ_HZ, self.PUMP_RATED_FREQ_HZ))

            # 6) 扬程换算：H = Δp / (ρ·g) ≈ Δp(kPa) / 9.81
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
            return {
                "flow_m3h": 0.0,
                "worst_loop_dp_kpa": 0.0,
                "valve_opening_avg_pct": 0.0,
                "pump_freq_hz": self.PUMP_MIN_FREQ_HZ,
                "pump_head_m": 0.0,
                "error": f"calc_water_side 异常：{type(exc).__name__}",
            }

    # ────────────────────────── 风侧 ──────────────────────────
    def calc_air_side(self, zone_loads):
        """风侧 VAV 系统过程量反算。

        物理依据：
            1. 显热平衡 Q = ρ·cp·V·ΔT     →  V (m³/s) = Q(kW) / (ρ·cp · ΔT)
               采用工程近似 ρ·cp ≈ 1.2 kJ/(m³·K)，送风温差 ΔT 取 10 K。
               体积流量换算 V(m³/h) = V(m³/s) × 3600。
            2. 各区 VAV 风阀开度 ∝ 该区送风量 / 该区设计最大送风量（线性化近似），限幅 [10%,100%]。
            3. 主风管静压（余压）按总风量占额定风量比例在 [DUCT_STATIC_MIN, DUCT_STATIC_MAX] 区间映射。
            4. 送风机频率沿用相似律 f = 50 × (V_total / V_rated)，下限 20 Hz 防失速。

        参数：
            zone_loads (dict): {区名: 冷负荷 kW}
        返回：
            dict — 含每区风量、VAV 开度、总风量、主风管余压、风机频率等过程量。
        """
        try:
            if not isinstance(zone_loads, dict) or not zone_loads:
                zone_loads = {}

            zone_flow_m3h = {}
            zone_flow_max_m3h = {}
            for zk, q_kw in zone_loads.items():
                q = max(0.0, float(q_kw))
                # V(m³/s) = Q(kW) / (ρ·cp · ΔT)  → m³/h
                v_m3h = q / max(self._EPS, self.RHO_CP_AIR * self.DELTA_T_AIR_K) * 3600.0
                zone_flow_m3h[zk] = v_m3h
                # 该区设计最大风量按 1.4 倍当前风量做线性化基准（保证 PLR=1 时阀位 ≈ 70%）
                zone_flow_max_m3h[zk] = max(self._EPS, v_m3h * 1.4 + 1.0)

            total_flow_m3h = float(sum(zone_flow_m3h.values()))

            # VAV 开度：按区分别映射至 [10%, 100%]
            vav_openings_pct = {}
            for zk, v in zone_flow_m3h.items():
                ratio = v / zone_flow_max_m3h[zk]
                vav_openings_pct[zk] = round(float(np.clip(ratio * 100.0, 10.0, 100.0)), 1)

            # 主风管余压：按风量比例在工程上下限内插
            flow_ratio = total_flow_m3h / max(self._EPS, self.rated_air_flow_m3h)
            flow_ratio_clip = float(np.clip(flow_ratio, 0.2, 1.2))
            duct_static_pa = (self.DUCT_STATIC_MIN_PA
                              + (self.DUCT_STATIC_MAX_PA - self.DUCT_STATIC_MIN_PA)
                              * min(1.0, flow_ratio_clip))

            # 送风机频率（相似律）
            fan_freq_hz = float(np.clip(self.FAN_RATED_FREQ_HZ * flow_ratio,
                                        self.FAN_MIN_FREQ_HZ, self.FAN_RATED_FREQ_HZ))

            return {
                "zone_flow_m3h": {k: round(v, 1) for k, v in zone_flow_m3h.items()},
                "vav_openings_pct": vav_openings_pct,
                "total_air_flow_m3h": round(total_flow_m3h, 1),
                "duct_static_pressure_pa": round(duct_static_pa, 1),
                "fan_freq_hz": round(fan_freq_hz, 2),
                "supply_air_delta_t_k": round(self.DELTA_T_AIR_K, 1),
            }
        except Exception as exc:
            return {
                "vav_openings_pct": {},
                "duct_static_pressure_pa": self.DUCT_STATIC_MIN_PA,
                "fan_freq_hz": self.FAN_MIN_FREQ_HZ,
                "error": f"calc_air_side 异常：{type(exc).__name__}",
            }

    # ──────────────────────── 多联机 VRF ────────────────────────
    def calc_vrf_side(self, vrf_load):
        """变频多联机过程量反算。

        物理依据：
            1. 制冷剂侧能量守恒 Q = m_dot · Δh
               采用 R410A 蒸发器进出口比焓差 Δh ≈ 190 kJ/kg（180~200 kJ/kg 工程区间）。
               质量流量 m_dot(kg/s) = Q(kW) / Δh，换算为 kg/h × 3600。
            2. 电子膨胀阀（EXV）开度按"基础开度 + 增益·PLR"联动表达：
               opening = EXV_BASE + EXV_GAIN · PLR，限幅 [EXV_MIN, EXV_MAX]
               物理含义：负荷越高蒸发器需求质量流量越大，需更大开度以维持过热度。
            3. 蒸发温度近似按 PLR 弱相关下移（高负荷导致蒸发压力下降）。

        参数：
            vrf_load (float): 多联机当前冷量需求 kW
        返回：
            dict — 含 EXV 开度、制冷剂质量流量、PLR、估算蒸发温度等过程量。
        """
        try:
            load_kw = max(0.0, float(vrf_load))
            plr = min(1.2, load_kw / max(self._EPS, self.vrf_rated_kw))

            # 1) 制冷剂质量流量
            mass_flow_kgs = load_kw / max(self._EPS, self.R410A_LATENT_KJ)
            mass_flow_kgh = mass_flow_kgs * 3600.0

            # 2) EXV 开度
            exv_raw = self.EXV_BASE_OPENING_PCT + self.EXV_GAIN_PCT * min(1.0, max(0.0, plr))
            exv_pct = float(np.clip(exv_raw, self.EXV_MIN_PCT, self.EXV_MAX_PCT))

            # 3) 蒸发温度估算（高负荷蒸发压力下降，工程线性近似）
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
            return {
                "exv_opening_pct": self.EXV_MIN_PCT,
                "refrigerant_mass_flow_kgh": 0.0,
                "error": f"calc_vrf_side 异常：{type(exc).__name__}",
            }

    # ──────────────────────── 环境扰动 ────────────────────────
    def calc_env_disturbance(self, t_out=32.0, hour=14.0, building_area_m2=10000.0,
                              window_ratio=0.3, cloud_cover=0.0, solar_hour_angle_deg=None):
        """环境扰动冷负荷估算。

        物理依据（用户硬性要求：必须以太阳常数 1353 W/m² 作为基准）：
            1. 太阳常数 I0 = 1353 W/m²（SOLAR_CONSTANT，地外太阳辐射通量）。
            2. 太阳高度角 β：以"正午为最大值"的工程简算
                 sinβ ≈ sin(π × (hour − sunrise) / (sunset − sunrise))，h ∈ [sunrise, sunset]，否则 0。
               若调用方提供 solar_hour_angle_deg（时角，正午为 0°），则采用更通用近似
                 sinβ ≈ max(0, cos(hour_angle))。
            3. 落地辐照度（W/m²）：
                 G = I0 · τ_atm · sinβ · (1 − cloud_cover)
               其中 τ_atm 为大气透射率（晴天 0.6~0.75）。
            4. 围护结构等效得热（W）：
                 Q_solar = G · A_envelope · WWR · ENVELOPE_GAIN_COEFF
                 Q_cond  = U · A_envelope · max(0, t_out − t_in)
               其中外围护面积按 √A_floor × 楼高 × 4 估算，楼高取 4.5 m。
            5. 总扰动负荷 disturbance_load_kw = (Q_solar + Q_cond) / 1000。

        参数：
            t_out (float): 室外干球温度 ℃
            hour  (float): 当前小时（0~24，浮点）
            building_area_m2 (float): 建筑总面积 m²
            window_ratio (float): 窗墙比 WWR ∈ [0,1]
            cloud_cover  (float): 云量遮蔽率 ∈ [0,1]，默认 0（晴天）
            solar_hour_angle_deg (float, optional): 太阳时角度数（正午=0°），可选覆写时刻法
        返回：
            dict — 含太阳常数、辐照度、扰动冷负荷及分项过程量。
        """
        try:
            t_out_v = float(t_out)
            hour_v = float(hour)
            area = max(0.0, float(building_area_m2))
            wwr = float(np.clip(window_ratio, 0.0, 1.0))
            cloud = float(np.clip(cloud_cover, 0.0, 1.0))

            # 1) 太阳高度角正弦：优先采用时角法，否则按时刻线性近似
            if solar_hour_angle_deg is not None:
                sin_beta = max(0.0, math.cos(math.radians(float(solar_hour_angle_deg))))
            else:
                if self.SUNRISE_HOUR <= hour_v <= self.SUNSET_HOUR:
                    sin_beta = math.sin(math.pi * (hour_v - self.SUNRISE_HOUR)
                                        / max(self._EPS, (self.SUNSET_HOUR - self.SUNRISE_HOUR)))
                    sin_beta = max(0.0, sin_beta)
                else:
                    sin_beta = 0.0

            # 2) 落地辐照度：基于太阳常数 1353 W/m² 推导
            irradiance_wm2 = self.SOLAR_CONSTANT * self.ATMOS_TRANSMISSIVITY * sin_beta * (1.0 - cloud)

            # 3) 外围护面积（工程估算）：√A × H × 4
            building_height_m = 4.5
            envelope_area_m2 = math.sqrt(max(0.0, area)) * building_height_m * 4.0

            # 4) 太阳辐射得热 + 围护温差传热
            q_solar_w = irradiance_wm2 * envelope_area_m2 * wwr * self.ENVELOPE_GAIN_COEFF
            q_cond_w = (self.OPAQUE_U_W_M2K * envelope_area_m2 * (1.0 - wwr)
                        * max(0.0, t_out_v - self.INDOOR_SET_TEMP_C))

            disturbance_load_kw = (q_solar_w + q_cond_w) / 1000.0

            return {
                "solar_constant_wm2": self.SOLAR_CONSTANT,        # 1353 W/m² 基准
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
            return {
                "solar_constant_wm2": self.SOLAR_CONSTANT,
                "solar_irradiance_wm2": 0.0,
                "disturbance_load_kw": 0.0,
                "error": f"calc_env_disturbance 异常：{type(exc).__name__}",
            }

    # ──────────────────────── 室内热舒适（PMV）────────────────────────
    def calc_pmv(self, temp, relative_humidity=50, air_speed=0.15, clo=0.5, met=1.1):
        """ISO 7730 / ASHRAE 55 标准 PMV (Predicted Mean Vote) 计算（Fanger 1972）。

        本实现为 ISO 7730 附录 D 的完整 Fanger 方程，通过迭代求解衣物表面温度 tcl。

        参数：
            temp              (float): 室内空气温度 ℃（平均辐射温度近似取等于空气温度）
            relative_humidity (float): 相对湿度 %    默认 50
            air_speed         (float): 室内空气流速 m/s 默认 0.15
            clo               (float): 衣着热阻 clo  默认 0.5
            met               (float): 代谢率 met    默认 1.1
        返回：
            float — PMV 值，理论范围 [-3, +3]。
                    -0.5 ≤ PMV ≤ +0.5 视为热舒适（ISO 7730 B 类合规区）。
        """
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
            return 0.0

    # ──────────────────────── 聚合入口 ────────────────────────
    def simulate_all(self, cooling_load_kw, supply_temp_c, zone_loads,
                     vrf_load_kw, t_out=32.0, hour=12.0,
                     building_area_m2=12000.0, window_ratio=0.65,
                     cloud_cover=0.0, indoor_temp_c=26.0,
                     indoor_rh_percent=50.0, indoor_air_speed_ms=0.15,
                     occupant_clo=0.5, occupant_met=1.1):
        """聚合入口：一次性串联水侧 / 风侧 / VRF / 环境扰动 4 类过程量反算，
        返回一个扁平化 dict（核心物理量暴露在顶层 key，原子状态保留在 _water/_air/_vrf/_env）。

        设计意图：
            主循环 (WhiteBoxEngine.execute_step) 仅需一行调用本方法即可获得整套物理
            过程视图，避免把 4 个 calc_* 的调用逻辑和中间拼装散落到主控类。

        参数：
            cooling_load_kw   (float): 当前水冷系统总冷量需求 kW（公共区，已过寻优分配）
            supply_temp_c     (float): 冷冻水供水温度 ℃
            zone_loads        (dict) : {区名: 冷负荷 kW}（用于 VAV 反算）
            vrf_load_kw       (float): 多联机当前冷量需求 kW
            t_out             (float): 室外干球温度 ℃
            hour              (float): 当前小时 0~24
            building_area_m2  (float): 建筑总面积 m²
            window_ratio      (float): 窗墙比 [0,1]
            cloud_cover       (float): 云量遮蔽率 [0,1]
        返回：
            dict — 扁平化过程量视图。
        """
        try:
            water = self.calc_water_side(cooling_load_kw, supply_temp_c)
            air   = self.calc_air_side(zone_loads or {})
            vrf   = self.calc_vrf_side(vrf_load_kw)
            env   = self.calc_env_disturbance(
                t_out=t_out, hour=hour,
                building_area_m2=building_area_m2,
                window_ratio=window_ratio,
                cloud_cover=cloud_cover,
            )
            # 室内热舒适（PMV，ISO 7730 标准实现）
            try:
                pmv_value = round(float(self.calc_pmv(
                    temp=indoor_temp_c, relative_humidity=indoor_rh_percent,
                    air_speed=indoor_air_speed_ms,
                    clo=occupant_clo, met=occupant_met)), 2)
            except Exception:
                pmv_value = 0.0
            return {
                # —— 用户硬性指定的 4 个核心物理量 ——
                "pump_freq_hz":            water.get("pump_freq_hz"),
                "duct_static_pressure_pa": air.get("duct_static_pressure_pa"),
                "exv_opening_pct":         vrf.get("exv_opening_pct"),
                "worst_loop_dp_kpa":       water.get("worst_loop_dp_kpa"),
                # —— 水侧扩展 ——
                "chw_flow_m3h":            water.get("flow_m3h"),
                "valve_opening_avg_pct":   water.get("valve_opening_avg_pct"),
                "pump_head_m":             water.get("pump_head_m"),
                "chw_supply_temp_c":       water.get("supply_temp_c"),
                "chw_return_temp_c":       water.get("return_temp_c"),
                # —— 风侧扩展 ——
                "total_air_flow_m3h":      air.get("total_air_flow_m3h"),
                "fan_freq_hz":             air.get("fan_freq_hz"),
                "vav_openings_pct":        air.get("vav_openings_pct"),
                # —— VRF 扩展 ——
                "refrigerant_mass_flow_kgh": vrf.get("refrigerant_mass_flow_kgh"),
                "evap_temp_c":             vrf.get("evap_temp_c"),
                "vrf_plr":                 vrf.get("plr_ratio"),
                # —— 环境扰动扩展 ——
                "solar_irradiance_wm2":    env.get("solar_irradiance_wm2"),
                "disturbance_load_kw":     env.get("disturbance_load_kw"),
                "outdoor_temp_c":          env.get("outdoor_temp_c"),
                "solar_constant_wm2":      env.get("solar_constant_wm2"),
                # —— 完整子状态（供详情面板/日志可选消费）——
                "_water": water,
                "_air":   air,
                "_vrf":   vrf,
                "_env":   env,
                # —— 室内热舒适（PMV，ISO 7730 B 类合规区为 [-0.5, +0.5]）——
                "PMV_Index":         pmv_value,
                "indoor_temp_c":     round(float(indoor_temp_c), 2),
                "indoor_rh_percent": round(float(indoor_rh_percent), 1),
            }
        except Exception as exc:
            return {
                "error": f"simulate_all 异常：{type(exc).__name__}: {exc}",
                "pump_freq_hz": 0.0,
                "duct_static_pressure_pa": 0.0,
                "exv_opening_pct": 0.0,
                "worst_loop_dp_kpa": 0.0,
                "PMV_Index": 0.0,
            }


# =====================================================================
# 4. 物理模型与安全控制引擎
# =====================================================================
class EquipmentModel:
    def __init__(self, name, interpolator_ref):
        self.name = name
        self.interpolator = interpolator_ref

    def calculate_cop(self, t_out, plr, sys_config, log_callback=None, alarms_list=None):
        t_arr = sys_config['cop_tables']['T_out']
        p_arr = sys_config['cop_tables']['PLR']
        t_out_safe = float(np.clip(t_out, min(t_arr), max(t_arr)))
        plr_safe = float(np.clip(plr, min(p_arr), max(p_arr)))
        if (t_out != t_out_safe or plr != plr_safe) and alarms_list is not None:
            msg = f"COP插值边界裁剪[{self.name}]: T_out={t_out}->{t_out_safe}, PLR={plr:.2f}->{plr_safe:.2f}"
            if msg not in alarms_list:
                alarms_list.append(msg)
                if log_callback:
                    log_callback("边界裁剪", msg)
        cop = self.interpolator([t_out_safe, plr_safe])[0]
        return round(float(cop), 2) if not np.isnan(cop) else 2.0


class EquipmentRegistry:
    def __init__(self):
        self._registry = {}

    def register(self, type_name, model_instance):
        self._registry[type_name] = model_instance

    def get(self, type_name):
        return self._registry.get(type_name)


# =====================================================================
# ★ 三台磁悬浮机组全局寻优分配器（scipy.optimize.minimize）
# =====================================================================
class ChillerGroupOptimizer:
    """
    三台磁悬浮冷水机组全局负荷寻优分配器。

    机组额定容量（1RT = 3.5169 kW）:
      CH-1 : 800 RT ≈ 2813.5 kW
      CH-2 : 800 RT ≈ 2813.5 kW
      CH-3 : 430 RT ≈ 1512.3 kW
      总计  : 2030 RT ≈ 7139.3 kW（与配置 7140 kW 吻合）

    目标函数
    --------
    minimize  Σ_i  Q_i / COP_i(T_cw, T_chw, PLR_i)
              即最小化三台机组的合计电功耗

    约束条件
    --------
    等式约束: Σ_i Q_i  = Q_total          （冷量守恒）
    边界约束: Q_i_min ≤ Q_i ≤ Q_i_rated   （各机额定与最小 PLR 限幅）

    COP 查询策略
    ------------
    1. 调用 RegularGridInterpolator(T_out, PLR) 获取基准 COP_base(T_out, PLR_i)
    2. 施加冷却水温修正（冷凝侧）：每升高 1 ℃, COP ↓ 约 2 %
    3. 施加冷冻水温修正（蒸发侧）：每偏离设计值 1 ℃, COP 线性修正
    此三步等效实现了"(T_cw, T_chw, PLR) → COP"三维物理插值，
    在无需重建 COP 表结构的前提下兼容现有 RegularGridInterpolator。
    """

    # ── 物理常数 ──────────────────────────────────────────────────────
    RT_TO_KW: float = 3.5169           # 1 冷吨换算系数 (kW)
    CW_DESIGN_TEMP: float = 32.0       # 冷却水供水设计温度 (℃)
    CHW_DESIGN_TEMP: float = 7.0       # 冷冻水供水设计温度 (℃)
    K_CW: float = 0.020                # 冷凝侧修正系数 (每 ℃)
    K_CHW: float = 0.015               # 蒸发侧修正系数 (每 ℃)

    # ── 三台机组参数 ──────────────────────────────────────────────────
    UNIT_RT: list = [800, 800, 430]    # 各机额定冷吨
    UNIT_NAMES: list = ["CH-1(800RT)", "CH-2(800RT)", "CH-3(430RT)"]

    def __init__(self, central_model, sys_config: dict):
        """
        Parameters
        ----------
        central_model : EquipmentModel
            已完成 RegularGridInterpolator 初始化的"central"类型机组模型。
        sys_config : dict
            全局系统配置字典（需含 'safety' → 'central_min_plr'）。
        """
        self.model = central_model
        self.sys_config = sys_config
        # 各机额定冷量 (kW)，与配置 capacity_central_kw=7140 kW 吻合
        self.unit_caps_kw: list = [rt * self.RT_TO_KW for rt in self.UNIT_RT]
        self._last_result: dict = {}

    # ── 内部：修正版 COP 查询（等效三维插值） ────────────────────────
    def _query_cop(self, t_out: float, plr: float,
                   t_cw: float = 32.0, t_chw: float = 7.0) -> float:
        """
        通过现有 RegularGridInterpolator(T_out, PLR) 查询基准 COP，
        叠加冷却水 / 冷冻水温度物理修正，实现等效三维 COP 响应面。

        修正公式（磁悬浮机组工程拟合）：
          COP_3D = COP_base(T_out, PLR)
                   × [1 - K_cw × (T_cw - T_cw_design)]  ← 冷凝侧修正
                   × [1 + K_chw × (T_chw - T_chw_design)] ← 蒸发侧修正
        """
        # 1. 从现有二维 RegularGridInterpolator 获取基准 COP
        cop_base = self.model.calculate_cop(t_out, plr, self.sys_config)

        # 2. 冷却水温修正（冷凝侧）
        cw_corr = 1.0 - self.K_CW * (t_cw - self.CW_DESIGN_TEMP)
        cw_corr = float(np.clip(cw_corr, 0.50, 1.20))   # 安全限幅

        # 3. 冷冻水温修正（蒸发侧）
        chw_corr = 1.0 + self.K_CHW * (t_chw - self.CHW_DESIGN_TEMP)
        chw_corr = float(np.clip(chw_corr, 0.75, 1.25))  # 安全限幅

        cop_3d = cop_base * cw_corr * chw_corr
        return max(1.0, round(cop_3d, 4))

    # ── 核心：负荷寻优分配 ────────────────────────────────────────────
    def optimize(self,
                 q_total_kw: float,
                 t_out: float,
                 n_active: int,
                 t_cw: float = 32.0,
                 t_chw: float = 7.0,
                 alarms_list: list = None) -> dict:
        """
        执行三机组全局负荷寻优，返回最优冷量分配方案。

        Parameters
        ----------
        q_total_kw  : 本时刻水冷系统需交付的总冷量 (kW)
        t_out       : 当前室外干球温度 (℃)，用于 COP 基准插值
        n_active    : 本时刻投入运行的机组台数 (0 ~ 3)；
                      投机策略为大机优先：CH-1 → CH-2 → CH-3
        t_cw        : 冷却水供水温度 (℃)，默认设计值 32 ℃
        t_chw       : 冷冻水供水温度 (℃)，默认设计值 7 ℃
        alarms_list : 告警列表引用；诊断信息直接 append 写入

        Returns
        -------
        dict，含以下 key：
          'loads'          : [L1, L2, L3]   各机冷量分配 (kW)
          'powers'         : [P1, P2, P3]   各机电功耗 (kW)
          'cops'           : [COP1, COP2, COP3]
          'plrs'           : [PLR1, PLR2, PLR3]
          'total_power_kw' : 合计电功耗 (kW)
          'system_cop'     : 系统综合 COP = Q_total / P_total
          'status'         : 寻优状态描述
        """
        if n_active <= 0 or q_total_kw <= 0:
            return self._zero_result()

        caps = self.unit_caps_kw                         # [2813.5, 2813.5, 1512.3]
        n_total = len(caps)
        c_min = self.sys_config['safety']['central_min_plr']

        # ── 投机策略：大机优先（CH-1, CH-2 先投；CH-3 最后）──────────
        active_idx = list(range(n_active))               # 前 n_active 台运行
        cap_active = [caps[i] for i in active_idx]

        # ── 可行域 ─────────────────────────────────────────────────────
        max_cap = sum(cap_active)
        min_load = sum(caps[i] * c_min for i in active_idx)

        q_req = float(np.clip(q_total_kw, min_load, max_cap))
        if abs(q_req - q_total_kw) > 1.0 and alarms_list is not None:
            alarms_list.append(
                f"[寻优] 需求冷量 {q_total_kw:.0f} kW 超出"
                f" [{min_load:.0f}, {max_cap:.0f}] kW 区间，已裁剪至 {q_req:.0f} kW"
            )

        # ── 决策变量 x[j] = 第 j 台运行机组的冷量分配 (kW) ───────────
        # 初始猜测：按额定容量比例分摊
        cap_sum = sum(cap_active)
        x0 = np.array([q_req * c / cap_sum for c in cap_active])

        # 边界: [PLR_min × cap_i,  cap_i]
        lb = [caps[i] * c_min for i in active_idx]
        ub = [caps[i]          for i in active_idx]
        bounds = SpBounds(lb, ub, keep_feasible=True)

        # ── 目标函数：最小化合计电功耗 Σ Q_i / COP_i ─────────────────
        def objective(x: np.ndarray) -> float:
            total_p = 0.0
            for j, i in enumerate(active_idx):
                plr_j = float(np.clip(x[j] / caps[i], c_min, 1.2))
                cop_j = self._query_cop(t_out, plr_j, t_cw, t_chw)
                total_p += x[j] / max(cop_j, 0.1)
            return total_p

        # ── 等式约束：运行机组冷量之和等于目标值 ─────────────────────
        constraints = [{'type': 'eq', 'fun': lambda x: float(np.sum(x)) - q_req}]

        # ── 调用 SLSQP 非线性规划求解器 ───────────────────────────────
        opt_status = "寻优成功(SLSQP)"
        try:
            res = minimize(
                objective, x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'ftol': 1e-8, 'maxiter': 500, 'disp': False, 'eps': 1e-6}
            )
            if res.success:
                x_opt = res.x
                opt_status = f"寻优成功(SLSQP,迭代{res.nit}次)"
            elif res.fun < objective(x0) + 0.5:
                # 虽未严格收敛但已改善，接受次优解
                x_opt = res.x
                opt_status = f"寻优次优解(迭代{res.nit}次,{res.message[:25]})"
            else:
                x_opt = x0
                opt_status = f"寻优回退均匀分配({res.message[:25]})"
                if alarms_list is not None:
                    alarms_list.append(f"[寻优] SLSQP 未收敛: {res.message}")
        except Exception as exc:
            x_opt = x0
            opt_status = f"寻优异常-回退均匀({type(exc).__name__})"
            if alarms_list is not None:
                alarms_list.append(f"[寻优] scipy 异常: {exc}")

        # ── 汇总各机结果 ──────────────────────────────────────────────
        loads  = [0.0] * n_total
        powers = [0.0] * n_total
        cops   = [0.0] * n_total
        plrs   = [0.0] * n_total

        for j, i in enumerate(active_idx):
            L_j   = float(np.clip(x_opt[j], lb[j], ub[j]))
            plr_j = float(np.clip(L_j / caps[i], c_min, 1.2))
            cop_j = self._query_cop(t_out, plr_j, t_cw, t_chw)
            loads[i]  = round(L_j, 2)
            plrs[i]   = round(plr_j, 4)
            cops[i]   = round(cop_j, 3)
            powers[i] = round(L_j / max(cop_j, 0.1), 2)

        total_power = round(sum(powers), 2)
        total_load  = sum(loads[i] for i in active_idx)
        system_cop  = round(total_load / total_power, 3) if total_power > 0 else 0.0

        self._last_result = {
            'loads'          : loads,
            'powers'         : powers,
            'cops'           : cops,
            'plrs'           : plrs,
            'total_power_kw' : total_power,
            'system_cop'     : system_cop,
            'status'         : opt_status,
        }
        return self._last_result

    def _zero_result(self) -> dict:
        """零负荷时返回全零结果，避免空判断。"""
        return {
            'loads'          : [0.0, 0.0, 0.0],
            'powers'         : [0.0, 0.0, 0.0],
            'cops'           : [0.0, 0.0, 0.0],
            'plrs'           : [0.0, 0.0, 0.0],
            'total_power_kw' : 0.0,
            'system_cop'     : 0.0,
            'status'         : '机组未启用',
        }


class RoomRCModel:
    def __init__(self, config):
        self.t_in = 24.0
        self.params = config['rc_model_params']

    def step(self, t_out, q_load_kw, q_cooling_delivered_kw, dt_min):
        dt_hr = dt_min / 60.0
        self.t_in += (
            (q_load_kw - q_cooling_delivered_kw) * self.params['heat_gain_coeff'] * dt_hr
            + (t_out - self.t_in) * self.params['envelope_ua_coeff'] * dt_hr
        )
        return round(self.t_in, 2)


class ThermalBuffer:
    def __init__(self):
        self.prev_load = None

    def step(self, target_load, dt_min, tau_min, reset=False):
        if reset or self.prev_load is None:
            self.prev_load = target_load
            return target_load
        alpha = dt_min / (tau_min + dt_min) if (tau_min + dt_min) > 0 else 1.0
        self.prev_load = self.prev_load + alpha * (target_load - self.prev_load)
        return round(self.prev_load, 2)


class LCCEstimator:
    def __init__(self, config):
        self.cfg = config['economics']
        self.total_kwh_saved = 0.0
        self.total_cost_saved = 0.0

    def get_price_by_hour(self, hour):
        tou = self.cfg.get('tou_price', {})
        if tou.get('use_tou', False):
            if hour in tou.get('peak_hours', []):
                return tou.get('peak_price', 1.20)
            elif hour in tou.get('valley_hours', []):
                return tou.get('valley_price', 0.35)
            else:
                return tou.get('flat_price', 0.80)
        return self.cfg.get('elec_price_flat', 0.8)

    def add_kwh(self, saved_kw, dt_min, current_time_min):
        saved_kwh = saved_kw * (dt_min / 60.0)
        self.total_kwh_saved += saved_kwh
        self.total_cost_saved += saved_kwh * self.get_price_by_hour(int((current_time_min / 60) % 24))

    def evaluate_annual(self):
        if self.total_kwh_saved <= 0:
            return None
        season_saved_yuan = self.total_cost_saved * self.cfg.get('cooling_season_days', 150) * self.cfg.get('seasonal_load_coeff', 0.65)
        annual_saved_万元 = season_saved_yuan / 10000.0
        capex = self.cfg['capex_diff_万元']
        net_cf = annual_saved_万元 - self.cfg['maint_diff_万元']
        if net_cf <= 0:
            return {"NPV": -capex, "Payback": 999.0, "Annual_Saving": round(annual_saved_万元, 2), "use_tou": self.cfg.get('tou_price', {}).get('use_tou', False)}
        npv = -capex
        discount_rate = self.cfg.get("discount_rate", 0.05)
        for t in range(1, self.cfg['life_years'] + 1):
            npv += net_cf / ((1 + discount_rate) ** t)
        return {"NPV": round(npv, 2), "Payback": round(capex / net_cf, 1), "Annual_Saving": round(annual_saved_万元, 2), "use_tou": self.cfg.get('tou_price', {}).get('use_tou', False)}


class WhiteBoxEngine:
    def __init__(self, config_manager, building_key):
        self.config_mgr = config_manager
        self.sys_config = config_manager.sys_config
        self.lcc = LCCEstimator(self.sys_config)
        self.thermal = ThermalBuffer()
        self.rc_model = RoomRCModel(self.sys_config)
        self.registry = EquipmentRegistry()
        self._build_registry()
        # ── 群控寻优分配器（scipy.optimize）──────────────────────────
        self.chiller_optimizer = ChillerGroupOptimizer(
            central_model=self.registry.get('central'),
            sys_config=self.sys_config
        )
        self.load_building(building_key)
        self._is_silent = False
        self.reset_state(full=True)
        # 由 MainPlatformGUI 在实例化后注入，用于将物理过程帧跨线程推送给 UI 主线程
        self.ui_reference = None

    def _build_registry(self):
        t_out_arr = np.array(self.sys_config['cop_tables']['T_out'])
        plr_arr = np.array(self.sys_config['cop_tables']['PLR'])
        for stype in ['central', 'vrf', 'base']:
            data = np.array(self.sys_config['cop_tables'][stype])
            interp = RegularGridInterpolator((t_out_arr, plr_arr), data, bounds_error=False, fill_value=np.nan)
            self.registry.register(stype, EquipmentModel(stype, interp))

    def load_building(self, building_key):
        keys = list(self.config_mgr.building_configs.keys())
        bk = building_key if building_key in keys else keys[0]
        self.b_cfg = self.config_mgr.building_configs[bk]
        self.zone_specs = {}
        self.zones = {}
        for zk, zv in self.b_cfg.get("zones", {}).items():
            if isinstance(zv, dict):
                self.zones[zk] = float(zv["design_load_kw"])
                _a_type = zv.get("area_type", "私域" if "私域" in zk else "公共")
                self.zone_specs[zk] = {
                    "area_type": _a_type,
                    "system_type": zv.get("system_type", "CHW" if _a_type == "公共" else "VRF"),
                    "design_load_kw": float(zv["design_load_kw"]),
                    "terminal_type": zv.get("terminal_type", "末端设备"),
                    "pipe_dn": zv.get("pipe_dn", "DN100"),
                    "pipe_length_m": float(zv.get("pipe_length_m", 100.0)),
                    "terminal_dp_kpa": float(zv.get("terminal_dp_kpa", 35.0)),
                    "air_duct_area_m2": float(zv.get("air_duct_area_m2", 1.2)),
                    "air_duct_length_m": float(zv.get("air_duct_length_m", 35.0)),
                    "air_resistance_coeff": float(zv.get("air_resistance_coeff", 0.9)),
                    "fan_efficiency": float(zv.get("fan_efficiency", 0.60)),
                    "design_airflow_m3h": float(zv.get("design_airflow_m3h", float(zv.get("design_load_kw", 1000.0)) * 250.0))
                }
            else:
                self.zones[zk] = float(zv)
                _a_type = "私域" if "私域" in zk else "公共"
                self.zone_specs[zk] = {
                    "area_type": _a_type,
                    "system_type": "CHW" if _a_type == "公共" else "VRF",
                    "design_load_kw": float(zv),
                    "terminal_type": "末端设备",
                    "pipe_dn": "DN100",
                    "pipe_length_m": 100.0,
                    "terminal_dp_kpa": 35.0,
                    "air_duct_area_m2": 1.2,
                    "air_duct_length_m": 35.0,
                    "air_resistance_coeff": 0.9,
                    "fan_efficiency": 0.60,
                    "design_airflow_m3h": float(zv) * 250.0
                }
        self.th = self.b_cfg.get("th", {"high": 6000.0, "mid": 2200.0})
        self.tau = self.b_cfg.get("tau", 25)
        self.hydraulic_model = HydraulicNetworkModel(self.zone_specs, self.sys_config)

    def zone_can_use_chw(self, zone):
        return self.zone_specs.get(zone, {}).get("system_type", "CHW") in ["CHW", "BOTH"]

    def zone_can_use_vrf(self, zone):
        return self.zone_specs.get(zone, {}).get("system_type", "VRF") in ["VRF", "BOTH"]

    def zone_is_none(self, zone):
        return self.zone_specs.get(zone, {}).get("system_type", "CHW") == "NONE"

    def reset_state(self, full=True):
        if full:
            self.sim_time = 0
            self.current_mode = "LOW"
            self.time_in_mode = 0
            self.current_chillers = 0
            self.time_in_staging = 0
            self.vrf_start_history = []
            self.event_log = []
            self.thermal.step(0, 0, self.tau, reset=True)
            self.rc_model.t_in = 24.0
            self.lcc.total_kwh_saved = 0.0
            self.lcc.total_cost_saved = 0.0
        self.switch_count = 0
        self.e_stop_active = False

    def export_state(self):
        return {
            "sim_time": self.sim_time, "current_mode": self.current_mode,
            "time_in_mode": self.time_in_mode, "current_chillers": self.current_chillers,
            "time_in_staging": self.time_in_staging, "vrf_start_history": self.vrf_start_history.copy(),
            "thermal_prev_load": self.thermal.prev_load, "rc_t_in": self.rc_model.t_in,
            "switch_count": self.switch_count, "e_stop_active": self.e_stop_active,
            "lcc_kwh": self.lcc.total_kwh_saved, "lcc_cost": self.lcc.total_cost_saved,
            "is_silent": self._is_silent, "event_log": self.event_log.copy()
        }

    def restore_state(self, st):
        self.sim_time = st["sim_time"]
        self.current_mode = st["current_mode"]
        self.time_in_mode = st["time_in_mode"]
        self.current_chillers = st["current_chillers"]
        self.time_in_staging = st["time_in_staging"]
        self.vrf_start_history = st["vrf_start_history"].copy()
        self.thermal.prev_load = st["thermal_prev_load"]
        self.rc_model.t_in = st["rc_t_in"]
        self.switch_count = st["switch_count"]
        self.e_stop_active = st["e_stop_active"]
        self.lcc.total_kwh_saved = st["lcc_kwh"]
        self.lcc.total_cost_saved = st["lcc_cost"]
        self._is_silent = st["is_silent"]
        self.event_log = st["event_log"].copy()

    def release_estop_state(self):
        self.e_stop_active = False
        self.log_event("解除急停", "DDC 安全复位，控制输出恢复")

    def log_event(self, event_type, desc):
        if not getattr(self, '_is_silent', False):
            self.event_log.append(f"[T={self.sim_time}m] [{event_type}] {desc}")

    def _parse_inputs(self, factor):
        t_out = factor.get("t_out", 33.5)
        f_weather = max(0.3, 1.0 + 0.04 * (t_out - 33.5) if t_out > 26.0 else 0.45)
        zone_names = list(self.zones.keys())
        r_zones_input = factor.get("r_zones", {})
        zone_loads = {}
        for i, z in enumerate(zone_names):
            if self.zone_is_none(z):
                zone_loads[z] = 0.0
                continue
            if isinstance(r_zones_input, list):
                rz = r_zones_input[i] if i < len(r_zones_input) else 0.75
            elif isinstance(r_zones_input, dict):
                rz = r_zones_input.get(z, 0.75)
            else:
                rz = 0.75
            zone_loads[z] = self.zones[z] * rz * factor.get("c_sch", 1) * factor.get("c_occ", 1) * f_weather
        target_load = sum(zone_loads.values())
        return t_out, zone_loads, target_load, factor.get("is_night", False)

    def execute_step(self, factor, strategy=None, forced_mode=None, ai_info=None,
                     dt=15, accumulate_lcc=True, silent=False, is_estop=False):
        # === 前置状态保存 ===
        prev_silent = self._is_silent
        self._is_silent = silent

        # 记录动作执行前的模式状态
        mode_before = self.current_mode

        # === 急停处理 ===
        if is_estop or self.e_stop_active:
            if is_estop and not self.e_stop_active:
                self.log_event("急停锁止", "硬件强断生效，控制输出挂起")
                self.e_stop_active = True
            self._is_silent = prev_silent
            frozen = self._frozen_state(ai_info)
            frozen["mode_before"] = mode_before
            return frozen

        # === 1. 负荷解析与热缓冲 ===
        t_out, zone_loads, target_load, is_night = self._parse_inputs(factor)
        q_required = self.thermal.step(target_load, dt, self.tau)

        scale = q_required / target_load if target_load > 0 else 0.0
        zone_loads_dyn = {z: load * scale for z, load in zone_loads.items()}

        cmd = {
            "alarms": [], "shedding_seq": [],
            "BACnet_AV_9001_LockTimer": "",
            "BACnet_DO_3001_Chiller_Units": 0,
            "BACnet_AO_4001_VRF_Demand_kW": 0.0,
            "BACnet_BI_3002_Chiller_RunStatus": 0,
            "BACnet_BI_4002_VRF_RunStatus": 0
        }
        for i, z in enumerate(self.zones):
            cmd[f"BACnet_BO_500{i+1}_Valve_{z[:2]}"] = 0
            cmd[f"BACnet_BI_510{i+1}_Valve_{z[:2]}_FB"] = 0

        safety_override = False
        safety_override_flag = False

        if self.rc_model.t_in > self.sys_config['safety']['indoor_temp_limit']:
            msg = f"安全超驰: 室温({self.rc_model.t_in:.1f}℃)超过安全上限，触发保护"
            cmd["alarms"].append(msg)
            self.log_event("安全超驰", msg)
            safety_override = True
            safety_override_flag = True

        # === 2. 策略决策与安全审核 ===
        # ── 边缘性能埋点：BiLSTM 推理延迟 ──────────────────────────
        _t_bilstm_0 = time.perf_counter()
        try:
            if forced_mode is not None:
                req_mode = forced_mode
            elif strategy is not None:
                req_mode = strategy.decide_mode(self, factor, dt)
            else:
                req_mode = "LOW"
        except Exception:
            req_mode = "LOW"
        _latency_ai = round((time.perf_counter() - _t_bilstm_0) * 1000.0, 2)
        # ────────────────────────────────────────────────────────────

        # 仅做加性观测：当云端 BiLSTM 策略发生降级时，将告警同步追加到 cmd['alarms']，
        # 由 AIReportAgent / HistoryLogger 走既有路径消费；此处不修改任何物理或寻优逻辑。
        if (strategy is not None
                and strategy.__class__.__name__ == 'BiLSTMCloudStrategy'
                and getattr(strategy, 'online', True) is False):
            cmd["alarms"].append('云端 BiLSTM 断开，无缝降级至本地 MPC 策略')

        if not req_mode:
            req_mode = "LOW"

        if safety_override:
            des_mode = "MID" if q_required > self.th.get("mid", 2200.0) else "LOW"
        else:
            des_mode = req_mode

        if des_mode != req_mode:
            cmd["alarms"].append(f"安全防线拦截：推荐指令({req_mode})已被修正为({des_mode})")

        # === 3. 模式切换防抖 ===
        is_switching = False
        lock_req = self.sys_config['safety']['min_stop_minutes'] if self.current_mode == "LOW" else self.sys_config['safety']['min_run_minutes']
        if des_mode != self.current_mode:
            if safety_override or self.time_in_mode >= lock_req:
                self.log_event("模态切换", f"{self.current_mode}->{des_mode}")
                self.current_mode = des_mode
                self.switch_count += 1
                self.time_in_mode = 0
                is_switching = True
            else:
                self.time_in_mode += dt
        else:
            self.time_in_mode += dt
        cmd["BACnet_AV_9001_LockTimer"] = f"{self.time_in_mode}/{lock_req}m"

        # === 4. 水冷/VRF 负荷分配 ===
        cap_c_total = self.sys_config['equipment']['capacity_central_kw']
        chiller_num = self.sys_config['equipment']['chiller_total_units']
        # ── 使用寻优器中真实的异构机组容量，不再用总量÷台数的均值 ────
        # CH-1: 800RT, CH-2: 800RT, CH-3: 430RT （大机优先投入）
        _unit_caps = self.chiller_optimizer.unit_caps_kw          # [2813.5, 2813.5, 1512.3]
        _unit_cumcaps = [sum(_unit_caps[:k+1]) for k in range(len(_unit_caps))]
        # cap_c_single 仅保留给下方防喘振最小负荷校核，取首台大机容量
        cap_c_single = _unit_caps[0] if _unit_caps else cap_c_total / max(1, chiller_num)
        c_min = self.sys_config['safety']['central_min_plr']
        q_public = 0.0
        q_private = 0.0
        desired_chillers = 0
        force_low = False
        # 寻优结果占位，保证后续 chiller_status 可正常引用
        _opt_res: dict = self.chiller_optimizer._zero_result()

        if self.current_mode != "LOW":
            if self.current_mode == "HIGH":
                q_public = sum(zone_loads_dyn[z] for z in self.zones if self.zone_can_use_chw(z))
            elif self.current_mode == "MID":
                q_public = sum(
                    zone_loads_dyn[z] for z in self.zones
                    if self.zone_can_use_chw(z) and (
                        self.zone_specs[z]["area_type"] == "公共" or not self.zone_can_use_vrf(z)
                    )
                )

            # ── 按真实异构容量决定最少启机台数（大机优先策略）─────────
            desired_chillers = 0
            for _k in range(chiller_num):
                desired_chillers = _k + 1
                if _unit_cumcaps[_k] >= q_public:
                    break
            desired_chillers = min(desired_chillers, chiller_num)

            # ── 防喘振校核：若最小负荷率不满足，尝试减机 ─────────────
            if desired_chillers > 0:
                while desired_chillers > 1:
                    _min_load_needed = sum(
                        _unit_caps[i] * c_min for i in range(desired_chillers)
                    )
                    if q_public >= _min_load_needed:
                        break
                    desired_chillers -= 1
                    if "防喘振降频约束触发" not in cmd["alarms"]:
                        cmd["alarms"].append("防喘振降频约束触发")
                # 单台校核
                _min_single = _unit_caps[0] * c_min
                if q_public < _min_single and not safety_override:
                    cmd["alarms"].append("水冷系统负荷过低，存在喘振风险，系统切回低负荷模式")
                    force_low = True

        if self.current_mode == "LOW" or force_low:
            q_public = 0.0
            if force_low:
                q_private = sum(zone_loads_dyn[z] for z in self.zones if self.zone_can_use_vrf(z))
                chw_only_load = sum(zone_loads_dyn[z] for z in self.zones if self.zone_can_use_chw(z) and not self.zone_can_use_vrf(z))
                if chw_only_load > 0:
                    cmd["alarms"].append("强制回退导致纯水系统区域无法由VRF代偿，进入温漂观察")
            else:
                q_private = sum(zone_loads_dyn[z] for z in self.zones if self.zone_can_use_vrf(z))
            desired_chillers = 0
            if force_low:
                self.current_mode = "LOW"
                self.time_in_mode = 0
                self.current_chillers = 0
                self.time_in_staging = 0
                is_switching = True
        elif self.current_mode == "HIGH":
            # VRF-only 区域在 HIGH 模式下仍由 VRF 承担
            q_private = sum(zone_loads_dyn[z] for z in self.zones if not self.zone_can_use_chw(z) and self.zone_can_use_vrf(z))
        elif self.current_mode == "MID":
            q_private = sum(
                zone_loads_dyn[z] for z in self.zones
                if self.zone_can_use_vrf(z) and (
                    self.zone_specs[z]["area_type"] == "私域" or not self.zone_can_use_chw(z)
                )
            )

        # === 5. 冷冻水水力计算 ===
        # 冷冻水分配：仅 CHW/BOTH 且激活的区域
        cooling_distribution = {}
        for z in self.zones.keys():
            if self.current_mode == "HIGH" and self.zone_can_use_chw(z):
                cooling_distribution[z] = zone_loads_dyn[z]
            elif self.current_mode == "MID" and self.zone_can_use_chw(z) and (
                self.zone_specs[z]["area_type"] == "公共" or not self.zone_can_use_vrf(z)
            ):
                cooling_distribution[z] = zone_loads_dyn[z]
            else:
                cooling_distribution[z] = 0.0

        hydraulic_info = self.hydraulic_model.calculate(cooling_distribution)
        for b in hydraulic_info.get("branches", []):
            if b["warning"]:
                cmd["alarms"].append(f"水力测点告警[{b['zone_name']}]: {b['warning']}")

        # 更新阀门点位：只有进入冷冻水的区域才打开水阀
        for i, z in enumerate(list(self.zones.keys())):
            if self.zone_can_use_chw(z) and cooling_distribution.get(z, 0.0) > 0:
                cmd[f"BACnet_BO_500{i+1}_Valve_{z[:2]}"] = 1
                cmd[f"BACnet_BI_510{i+1}_Valve_{z[:2]}_FB"] = 1
            else:
                cmd[f"BACnet_BO_500{i+1}_Valve_{z[:2]}"] = 0
                cmd[f"BACnet_BI_510{i+1}_Valve_{z[:2]}_FB"] = 0

        # === 6. 设备功率计算（含 SLSQP 寻优）===
        self.vrf_start_history = [t for t in self.vrf_start_history if self.sim_time - t <= 60]
        cap_v_raw = self.sys_config['equipment'].get('capacity_vrf_kw', 0.0)
        cap_v = max(1e-6, cap_v_raw)
        if cap_v_raw <= 0:
            cmd["alarms"].append("VRF容量配置异常，已按极小容量保护处理")
        v_min = self.sys_config['safety']['vrf_min_plr']
        P_c = 0.0
        P_v = 0.0
        q_delivered = 0.0
        cop_c = 4.0
        cop_v = 3.5
        combo = ""
        mech = ""
        plr_c = 0.0
        # 寻优延迟占位：LOW 模式不进入 SLSQP，保持 0.0；MID/HIGH 时由埋点覆盖
        _latency_opt = 0.0

        if self.current_mode == "LOW":
            combo, mech = "LOW", "多联机独立运转"
            if q_private > cap_v:
                cmd["alarms"].append(f"多联机需求超过容量上限: {cap_v:.1f}kW，已限幅")
                q_private = cap_v
            if q_private > 0 and (q_private / cap_v) < v_min:
                if self.rc_model.t_in > self.sys_config['safety']['indoor_temp_limit'] - 1.0:
                    if len(self.vrf_start_history) >= self.sys_config['safety']['max_vrf_starts_per_hour']:
                        cmd["alarms"].append("多联机防频繁启停保护触发")
                        q_private = cap_v * v_min
                    else:
                        duty = (q_private / cap_v) / v_min
                        cmd["alarms"].append(f"低负荷占空比运行 ({duty*100:.0f}%)")
                        self.vrf_start_history.append(self.sim_time)
                        q_private = cap_v * v_min * duty
                    cmd["BACnet_AO_4001_VRF_Demand_kW"] = round(cap_v * v_min, 1)
                else:
                    cmd["alarms"].append("极低负荷区域，机组进入深度待机 (不计节能收益)")
                    self.log_event("极低负荷保护", "多联机系统挂起")
                    q_private = 0.0
                    cmd["BACnet_AO_4001_VRF_Demand_kW"] = 0.0
            elif q_private > 0:
                cmd["BACnet_AO_4001_VRF_Demand_kW"] = round(q_private, 1)

            if q_private > 0:
                cop_v = self.registry.get('vrf').calculate_cop(
                    t_out, max(v_min, q_private / cap_v), self.sys_config, self.log_event, cmd["alarms"]
                )
                P_v = q_private / cop_v
                q_delivered = q_private
                cmd["BACnet_BI_4002_VRF_RunStatus"] = 1

        else:
            # MID 或 HIGH 模式
            if desired_chillers != self.current_chillers:
                if self.time_in_staging >= self.sys_config['safety']['staging_lock_minutes'] or safety_override:
                    self.current_chillers = desired_chillers
                    self.time_in_staging = 0
                else:
                    desired_chillers = self.current_chillers
                    cmd["alarms"].append(f"冷机加减机防抖锁定中: 当前 {self.current_chillers} 台")
            self.time_in_staging += dt
            cmd["BACnet_DO_3001_Chiller_Units"] = desired_chillers
            cmd["BACnet_BI_3002_Chiller_RunStatus"] = 1 if desired_chillers > 0 else 0

            if self.current_mode == "HIGH":
                combo, mech = "HIGH", f"冷水机组({desired_chillers}台)集中运行"
            else:
                combo, mech = "MID", f"冷水机组({desired_chillers}台)承担公共区 + VRF 协同"

            if self.current_mode == "MID":
                if q_private > cap_v:
                    q_private = cap_v
                if q_private > 0 and (q_private / cap_v) < v_min and not safety_override:
                    cmd["alarms"].append("多联机处于低断续负荷区，进入待机观察")
                    q_private = 0.0
                    cmd["BACnet_AO_4001_VRF_Demand_kW"] = 0.0
                    cmd["BACnet_BI_4002_VRF_RunStatus"] = 0
                else:
                    cmd["BACnet_AO_4001_VRF_Demand_kW"] = round(q_private, 1)
                    cmd["BACnet_BI_4002_VRF_RunStatus"] = 1 if q_private > 0 else 0
                if q_private > 0:
                    cop_v = self.registry.get('vrf').calculate_cop(
                        t_out, max(v_min, q_private / cap_v), self.sys_config, self.log_event, cmd["alarms"]
                    )
                    P_v = q_private / cop_v

            if self.current_mode == "HIGH" and q_private > 0:
                # VRF-only 区域在 HIGH 模式下由 VRF 承担
                if cap_v > 0:
                    cop_v = self.registry.get('vrf').calculate_cop(
                        t_out, max(v_min, q_private / cap_v), self.sys_config, self.log_event, cmd["alarms"]
                    )
                    P_v = q_private / cop_v
                    cmd["BACnet_BI_4002_VRF_RunStatus"] = 1

            if q_public > 0 and desired_chillers > 0:
                # ═══════════════════════════════════════════════════════
                # ★ 全局寻优：scipy.optimize.minimize (SLSQP) 替代
                #   硬编码均摊，动态计算三台机组最优冷量分配
                # ───────────────────────────────────────────────────────
                # 从水力模型获取当前冷冻水温（蒸发侧边界条件）
                _t_chw = hydraulic_info.get("supply_temp_c", 7.0)
                # 简化冷却塔模型：冷却水供水温度 = 室外干球温度 - 冷却塔逼近温差
                # 逼近温差取 8℃ 为保守估计（湿球温度较低地区实际约 3~5℃）
                # 限制范围 [28℃, 38℃] 防止极端工况下模型失真
                _t_cw = max(28.0, min(38.0, t_out - 8.0))

                # ── 边缘性能埋点：SLSQP 寻优耗时 ──────────────────────
                _t_opt_0 = time.perf_counter()
                _opt_res = self.chiller_optimizer.optimize(
                    q_total_kw=q_public,
                    t_out=t_out,
                    n_active=desired_chillers,
                    t_cw=_t_cw,
                    t_chw=_t_chw,
                    alarms_list=cmd["alarms"]
                )
                _latency_opt = round((time.perf_counter() - _t_opt_0) * 1000.0, 2)
                # ────────────────────────────────────────────────────────
                P_c    = _opt_res['total_power_kw']
                cop_c  = _opt_res['system_cop'] if _opt_res['system_cop'] > 0 else 4.0
                # 等效平均 PLR（仅供外部日志/UI 展示用，实际已按机组分配）
                plr_c  = (q_public / sum(_unit_caps[:desired_chillers])
                          if sum(_unit_caps[:desired_chillers]) > 0 else 0.0)

                # 写入群控寻优审计事件
                self.log_event(
                    "群控寻优",
                    "[{s}] 需求={q:.0f}kW "
                    "CH1:{l1:.0f}|CH2:{l2:.0f}|CH3:{l3:.0f} kW "
                    "→ 总功耗={p:.1f}kW 系统COP={c:.3f} "
                    "T_cw={tcw:.1f}℃ T_chw={tchw:.1f}℃".format(
                        s=_opt_res['status'], q=q_public,
                        l1=_opt_res['loads'][0], l2=_opt_res['loads'][1], l3=_opt_res['loads'][2],
                        p=P_c, c=cop_c, tcw=_t_cw, tchw=_t_chw
                    )
                )
                # ═══════════════════════════════════════════════════════

            q_delivered = q_public + q_private

        pump_p = hydraulic_info.get("pump_power_kw", 0.0)
        opt_p = P_c + P_v + pump_p
        self.sim_time += dt

        # === 7. 变压器容量保护 ===
        limit_kw = self.sys_config['safety']['transformer_capacity_kva'] * self.sys_config['safety']['power_factor']
        if opt_p > limit_kw:
            excess = opt_p - limit_kw
            cmd['shedding_seq'].append(f"变压器容量越限保护 {excess:.1f}kW，启动减载:")
            if P_v > 0:
                shed = min(P_v, excess)
                P_v -= shed
                excess -= shed
            if excess > 0 and P_c > 0:
                shed = min(P_c * 0.2, excess)
                P_c -= shed
                excess -= shed
            if excess > 0 and P_c > 0:
                shed = min(P_c, excess)
                P_c -= shed
            self.log_event("变压器容量保护", f"功率限制到 {limit_kw}kW")
            opt_p = P_c + P_v + pump_p
            q_delivered = (P_c * max(cop_c, 1.0)) + (P_v * max(cop_v, 1.0))
            safety_override_flag = True
            if excess > 0:
                cmd["alarms"].append("容量越限保护减载 (该时段不计 LCC 收益)")

        # === 8. 室温更新与经济性计算 ===
        t_in_current = self.rc_model.step(t_out, q_required, q_delivered, dt)

        cap_base = self.sys_config['equipment']['capacity_base_kw']
        base_plr = q_required / cap_base if cap_base > 0 else 0.1
        base_cop = self.registry.get('base').calculate_cop(t_out, base_plr, self.sys_config)
        trad_p = (q_required / base_cop) + (pump_p * 1.5) if base_cop > 0 else 0.0

        is_low_load_shutdown = any("待机" in a for a in cmd["alarms"])
        cooling_satisfaction = q_delivered / q_required if q_required > 0 else 1.0

        if is_low_load_shutdown:
            rate = 0.0
            saved_kw = 0.0
            satisfaction_disp = "机组深度待机 (不计收益)"
            rate_disp = "--"
            satisfaction_val = cooling_satisfaction
        elif cooling_satisfaction < 0.95:
            rate = 0.0
            saved_kw = 0.0
            rate_disp = "0.0%"
            satisfaction_val = cooling_satisfaction
            if len(cmd.get('shedding_seq', [])) > 0:
                satisfaction_disp = "容量越限减载 (不计收益)"
                self.log_event("容量越限", f"强制减载，供冷满足率 {cooling_satisfaction*100:.1f}%")
            else:
                satisfaction_disp = "设备满载能力受限 (不计收益)"
                self.log_event("满载边界", f"供冷满足率 {cooling_satisfaction*100:.1f}%")
        else:
            rate = round((trad_p - opt_p) / trad_p, 4) if trad_p > 0 else 0.0
            saved_kw = max(0.0, trad_p - opt_p)
            satisfaction_disp = f"达标 {min(100.0, round(cooling_satisfaction * 100, 1))}%"
            rate_disp = f"{round(rate * 100, 2)}%"
            satisfaction_val = cooling_satisfaction

        if accumulate_lcc and saved_kw > 0:
            self.lcc.add_kwh(saved_kw, dt, self.sim_time)

        # === 9. 结果组装与状态恢复 ===
        active_cop = round(q_delivered / (P_c + P_v), 2) if (P_c + P_v) > 0 else 0.0
        cmd.update({
            "Chiller_Actual_Power_kW": round(P_c, 1),
            "VRF_Actual_Power_kW": round(P_v, 1),
            "Chiller_Delivered_Cooling_kW": round(P_c * cop_c, 1) if P_c > 0 else 0.0,
            "VRF_Delivered_Cooling_kW": round(P_v * cop_v, 1) if P_v > 0 else 0.0
        })

        chiller_status = {
            "running_units"  : cmd.get("BACnet_DO_3001_Chiller_Units", 0),
            "plr_percent"    : round(plr_c * 100, 1) if cmd.get("BACnet_DO_3001_Chiller_Units", 0) > 0 else 0.0,
            "cop"            : round(cop_c, 2)        if cmd.get("BACnet_DO_3001_Chiller_Units", 0) > 0 else 0.0,
            "evap_flow_m3h"  : hydraulic_info.get("total_flow_m3h", 0.0),
            # ── 寻优分配明细（各机组独立数据） ───────────────────────
            "optimizer": {
                "unit_names"     : ChillerGroupOptimizer.UNIT_NAMES,
                "unit_caps_kw"   : [round(c, 1) for c in self.chiller_optimizer.unit_caps_kw],
                "loads_kw"       : _opt_res.get('loads',  [0.0, 0.0, 0.0]),
                "powers_kw"      : _opt_res.get('powers', [0.0, 0.0, 0.0]),
                "cops"           : _opt_res.get('cops',   [0.0, 0.0, 0.0]),
                "plrs"           : _opt_res.get('plrs',   [0.0, 0.0, 0.0]),
                "total_power_kw" : _opt_res.get('total_power_kw', 0.0),
                "system_cop"     : _opt_res.get('system_cop',     0.0),
                "status"         : _opt_res.get('status',         '-'),
            }
        }

        self._is_silent = prev_silent
        if not ai_info and strategy:
            ai_info = strategy.get_last_info()

        # ─────── 【新增】物理过程量反算 + 跨线程推送给 UI 主线程 ───────
        # 设计意图：
        #   决策（strategy.decide_mode + chiller_optimizer.optimize）已完成，
        #   各侧负荷分配已就绪；在汇总返回上层前，调用 PhysicsSimulationEngine.simulate_all
        #   一次性获得 4 类过程量，并通过 queue.Queue 投递到 GUI 主线程，
        #   使全天时序仿真期间界面能"边跑边刷"。
        physics_state = None
        try:
            ui_ref = getattr(self, "ui_reference", None)
            if ui_ref is not None and getattr(ui_ref, "physics_engine", None) is not None:
                # 安全读取配置：即使配置字典缺层级也不抛 KeyError
                _eq = self.sys_config.get('equipment', {}) if isinstance(self.sys_config, dict) else {}
                _env_cfg = self.sys_config.get('envelope', {}) if isinstance(self.sys_config, dict) else {}
                _bldg_area = _eq.get('floor_area_m2', 12000)
                _wwr = _env_cfg.get('window_to_wall_ratio', 0.65)
                _hour = float(factor.get('hour', 12)) if isinstance(factor, dict) else 12.0
                _chw_supply = hydraulic_info.get("supply_temp_c", 7.0) \
                    if isinstance(hydraulic_info, dict) else 7.0

                physics_state = ui_ref.physics_engine.simulate_all(
                    cooling_load_kw=q_public,
                    supply_temp_c=_chw_supply,
                    zone_loads=zone_loads_dyn,
                    vrf_load_kw=q_private,
                    t_out=t_out,
                    hour=_hour,
                    building_area_m2=_bldg_area,
                    window_ratio=_wwr,
                    indoor_temp_c=t_in_current,
                )
                physics_state["sim_time_min"] = self.sim_time
                physics_state["mode"] = self.current_mode
                # ── 边缘侧性能指标：一并随物理帧推送给主线程 ─────────
                physics_state["latency_ai"]  = _latency_ai
                physics_state["latency_opt"] = _latency_opt
                physics_state["mem_usage"]   = round(
                    _psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 1
                ) if _PSUTIL_OK else None
                # ─────────────────────────────────────────────────────

                # queue.Queue 是线程安全的，put_nowait 在无界队列上不会阻塞
                try:
                    ui_ref.physics_queue.put_nowait(physics_state)
                except Exception:
                    pass
        except Exception as _exc:
            try:
                self.log_event("物理过程反算异常", f"{type(_exc).__name__}: {_exc}")
            except Exception:
                pass
        # ────────────────────────────────────────────────────────────

        return {
            "time": self.sim_time, "dt": dt,
            "load": round(q_required, 2), "delivered": round(q_delivered, 2), "target": round(target_load, 2),
            "combo": combo, "mech": mech, "cmd": cmd,
            "trad_p": round(trad_p, 2), "opt_p": round(opt_p, 2),
            "rate": rate, "rate_disp": rate_disp,
            "t_out": t_out, "t_in": t_in_current,
            "active_cop": active_cop, "is_switching": is_switching,
            "cooling_satisfaction_val": satisfaction_val,
            "cooling_satisfaction_disp": satisfaction_disp,
            "lcc_info": self.lcc.evaluate_annual(),
            "total_kwh_saved": self.lcc.total_kwh_saved,
            "total_cost_saved": self.lcc.total_cost_saved,
            "ai_requested_mode": req_mode,
            "ai_suggested_type": type(strategy).__name__ if strategy else "无",
            "ai_info": ai_info if ai_info else {"reason": "本地执行", "risk_note": "-", "confidence": 1.0, "fallback": False},
            "safety_override": safety_override_flag,
            "hydraulic": hydraulic_info,
            "chiller_status": chiller_status,
            "sys_safety_cfg": self.sys_config['safety'],
            "mode_before": mode_before,
            "physics_state": physics_state
        }

    def _frozen_state(self, ai_info=None):
        empty_checkpoints = {
            "chiller_out": {"T": 7.0, "P": 0.0, "F": 0.0},
            "pump_out": {"T": 7.0, "P": 0.0, "F": 0.0},
            "distributor": {"T": 7.0, "P": 0.0, "F": 0.0},
            "term_in": {"T": 7.0, "P": 0.0, "F": "--"},
            "term_out": {"T": 12.0, "P": 0.0, "F": "--"},
            "return_main": {"T": 12.0, "P": 0.0, "F": 0.0}
        }
        return {
            "time": self.sim_time, "dt": 0,
            "load": 0.0, "delivered": 0.0, "target": 0.0,
            "combo": "急停断开", "mech": "底层点位物理级挂起隔离",
            "cmd": {"BACnet_AV_9001_LockTimer": "锁死", "alarms": [], "shedding_seq": [],
                    "Chiller_Actual_Power_kW": 0.0, "VRF_Actual_Power_kW": 0.0,
                    "Chiller_Delivered_Cooling_kW": 0.0, "VRF_Delivered_Cooling_kW": 0.0},
            "trad_p": 0.0, "opt_p": 0.0,
            "rate": 0.0, "rate_disp": "0.0%",
            "t_out": 0.0, "t_in": self.rc_model.t_in,
            "active_cop": 0.0, "is_switching": False,
            "cooling_satisfaction_val": 1.0,
            "cooling_satisfaction_disp": "急停状态，计费中止",
            "ai_requested_mode": "-",
            "ai_suggested_type": "急停断开",
            "ai_info": ai_info if ai_info else {"reason": "-", "risk_note": "-", "confidence": 0.0, "fallback": False},
            "safety_override": False,
            "lcc_info": self.lcc.evaluate_annual(),
            "total_kwh_saved": self.lcc.total_kwh_saved,
            "total_cost_saved": self.lcc.total_cost_saved,
            "hydraulic": {
                "supply_temp_c": 7.0, "return_temp_c": 12.0, "delta_t_c": 5.0,
                "total_flow_m3h": 0.0, "pump_head_kpa": 0.0, "pump_head_m": 0.0,
                "pump_power_kw": 0.0, "pump_freq_hz": 0.0, "pump_speed_rpm": 0,
                "pump_vfd_percent": 0.0, "checkpoints": empty_checkpoints,
                "branches": [], "is_sleep": True
            },
            "chiller_status": {"running_units": 0, "plr_percent": 0.0, "cop": 0.0, "evap_flow_m3h": 0.0},
            "sys_safety_cfg": self.sys_config['safety'],
            "mode_before": self.current_mode
        }

# =====================================================================
# 5. 策略层与大模型 API
# =====================================================================
class LLMClient:
    def __init__(self, provider, api_config):
        self.provider = provider
        p_config = api_config.get("providers", {}).get(provider, {})
        self.base_url = p_config.get("base_url", "")
        self.model = p_config.get("model", "")
        self.api_key = p_config.get("api_key", "")
        if self.base_url and not self.base_url.endswith("/chat/completions"):
            self.endpoint = self.base_url.rstrip("/") + "/chat/completions"
        else:
            self.endpoint = self.base_url

    def is_configured(self):
        return bool(self.base_url and self.model and self.api_key)

    def test_connection(self):
        if not self.is_configured():
            return False, "API 配置不完整：请填写 Base URL、模型名称和 API Key。"
        try:
            req = urllib.request.Request(self.endpoint, method="POST")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("Content-Type", "application/json")
            data = json.dumps({"model": self.model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}).encode("utf-8")
            with urllib.request.urlopen(req, data=data, timeout=5) as resp:
                if resp.status == 200:
                    return True, f"API 连接测试成功：模型 [{self.model}] 响应正常。"
            return False, "API 连接失败：返回非预期状态码。"
        except Exception as e:
            return False, f"网络连接或鉴权失败: {e}"

    def get_recommendation(self, state):
        if not self.is_configured():
            raise ValueError("API 配置不完整，无法发起请求")
        prompt = f"""
请根据以下群控空调系统工况输出标准 JSON 控制策略对象：
当前系统时段: {state['time_of_day']}
室外温度: {state['t_out']}℃
室内实时温度: {state['t_in']}℃
瞬态冷负荷: {state['load']:.1f} kW (趋势: {state['load_trend']})
当前运行模式: {state['current_mode']}
变压器容量上限: {state['transformer_limit']:.1f} kW
冷水机组额定容量: {state['chiller_cap']:.1f} kW
VRF额定容量: {state['vrf_cap']:.1f} kW
当前电价: {state['price']:.2f} 元/kWh (下一小时: {state['price_next_hour']:.2f} 元/kWh)

候选模式：LOW, MID, HIGH
输出格式（严格 JSON，禁止 Markdown 标记）：
{{
  "recommended_mode": "LOW",
  "reason": "决策理由",
  "risk_note": "潜在风险提示",
  "confidence": 0.95
}}
"""
        req = urllib.request.Request(self.endpoint, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise HVAC AI assistant. Output JSON string ONLY."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        try:
            with urllib.request.urlopen(req, data=json.dumps(payload).encode("utf-8"), timeout=10) as resp:
                return self._parse_response(resp)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                payload.pop("response_format", None)
                req2 = urllib.request.Request(self.endpoint, method="POST")
                req2.add_header("Authorization", f"Bearer {self.api_key}")
                req2.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req2, data=json.dumps(payload).encode("utf-8"), timeout=10) as resp2:
                    return self._parse_response(resp2)
            raise ValueError(f"API 返回错误状态码: {e.code}")
        except Exception as e:
            raise ValueError(f"网络请求失败: {e}")

    def _parse_response(self, resp):
        try:
            resp_json = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise ValueError(f"响应解析失败: {e}")
        if "choices" not in resp_json or not resp_json["choices"]:
            raise ValueError("响应格式错误：缺少 choices 字段")
        content = resp_json["choices"][0].get("message", {}).get("content", "")
        if not content:
            raise ValueError("响应内容为空")
        try:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            result = json.loads(match.group(0)) if match else json.loads(content)
        except Exception:
            raise ValueError("无法从响应中提取有效 JSON")
        if result.get("recommended_mode") not in ["LOW", "MID", "HIGH"]:
            raise ValueError("响应中 recommended_mode 不在允许范围内")
        if "confidence" not in result or result["confidence"] is None:
            result["confidence"] = 0.75
        if "reason" not in result or not str(result["reason"]).strip():
            result["reason"] = "云端模型基于当前参数给出的调度建议"
        if "risk_note" not in result or not str(result["risk_note"]).strip():
            result["risk_note"] = "最终执行受本地白箱规则审核"
        return result


class BaseStrategy:
    def decide_mode(self, engine, current_factor, dt):
        raise NotImplementedError

    def get_last_info(self):
        return {"reason": "本地规则执行", "risk_note": "无", "confidence": 1.0, "fallback": False}


class RuleBasedStrategy(BaseStrategy):
    def decide_mode(self, engine, current_factor, dt):
        _, zone_loads, target_load, is_night = engine._parse_inputs(current_factor)
        if is_night:
            return "LOW"
        if target_load > engine.th.get("high", 6000.0):
            return "HIGH"
        if target_load > engine.th.get("mid", 2200.0):
            q_pub = sum(zone_loads[z] for z in engine.zones if engine.zone_can_use_chw(z) and (engine.zone_specs[z]["area_type"] == "公共" or not engine.zone_can_use_vrf(z)))
            cap_c = engine.sys_config['equipment']['capacity_central_kw']
            c_min = engine.sys_config['safety']['central_min_plr']
            if q_pub > 0 and (q_pub / cap_c) < c_min:
                return "LOW"
            return "MID"
        return "LOW"

    def get_last_info(self):
        return {"reason": "本地阈值规则控制", "risk_note": "-", "confidence": 1.0, "fallback": False}


class MPCStrategy(BaseStrategy):
    def decide_mode(self, engine, current_factor, dt):
        best_mode = "LOW"
        min_cost = float('inf')
        original_state = engine.export_state()
        f1 = current_factor.copy()
        f2 = current_factor.copy()
        f2['t_out'] = f2.get('t_out', 33.5) + 0.5
        try:
            for candidate in ["LOW", "MID", "HIGH"]:
                engine.restore_state(original_state)
                r1 = engine.execute_step(f1, forced_mode=candidate, dt=dt, accumulate_lcc=False, silent=True)
                r2 = engine.execute_step(f2, forced_mode=candidate, dt=dt, accumulate_lcc=False, silent=True)
                h1 = int((r1['time'] / 60) % 24)
                h2 = int((r2['time'] / 60) % 24)
                cost = (r1['opt_p'] * dt / 60.0 * engine.lcc.get_price_by_hour(h1)
                        + r2['opt_p'] * dt / 60.0 * engine.lcc.get_price_by_hour(h2))
                t_limit = engine.sys_config['safety']['indoor_temp_limit']
                penalty = 0
                for r in (r1, r2):
                    if r['t_in'] > t_limit:
                        penalty += (r['t_in'] - t_limit) * 5000
                    if r['cooling_satisfaction_val'] < 0.95:
                        penalty += 2000
                    if r['is_switching']:
                        penalty += 200
                if cost + penalty < min_cost:
                    min_cost = cost + penalty
                    best_mode = candidate
        finally:
            engine.restore_state(original_state)
        return best_mode

    def get_last_info(self):
        return {"reason": "本地多步预测控制(MPC)寻优", "risk_note": "不含长效建筑热惯性", "confidence": 0.95, "fallback": False}


class CloudAIStrategy(BaseStrategy):
    def __init__(self, provider, api_config, fallback_strategy, call_every_n=4):
        self.llm = LLMClient(provider, api_config)
        self.fallback = fallback_strategy
        self.call_every_n = call_every_n
        self.step_counter = 0
        self.cached_mode = None
        self.last_response = None
        self.p_name = PROVIDER_PRESETS.get(provider, {}).get("display_name", "云端AI")
        self.prev_load = 0.0

    def decide_mode(self, engine, current_factor, dt):
        self.step_counter += 1
        if self.cached_mode and (self.step_counter % self.call_every_n != 1):
            return self.cached_mode
        _, _, target_load, _ = engine._parse_inputs(current_factor)
        current_hour = int((engine.sim_time / 60) % 24)
        next_hour = (current_hour + 1) % 24
        state = {
            "time_of_day": f"{current_hour:02d}:00",
            "t_out": current_factor.get("t_out", 33.5),
            "t_in": engine.rc_model.t_in,
            "load": target_load,
            "load_trend": "上升" if target_load >= self.prev_load else "下降",
            "current_mode": engine.current_mode,
            "transformer_limit": engine.sys_config['safety']['transformer_capacity_kva'] * engine.sys_config['safety']['power_factor'],
            "chiller_cap": engine.sys_config['equipment']['capacity_central_kw'],
            "vrf_cap": engine.sys_config['equipment']['capacity_vrf_kw'],
            "price": engine.lcc.get_price_by_hour(current_hour),
            "price_next_hour": engine.lcc.get_price_by_hour(next_hour)
        }
        self.prev_load = target_load
        try:
            resp = self.llm.get_recommendation(state)
            resp["fallback"] = False
            self.cached_mode = resp.get("recommended_mode", "LOW")
            self.last_response = resp
            return self.cached_mode
        except Exception as e:
            engine.log_event("API接口异常", f"通信失败，切回本地控制: {str(e)[:30]}")
            self.cached_mode = self.fallback.decide_mode(engine, current_factor, dt)
            self.last_response = {
                "recommended_mode": self.cached_mode,
                "reason": "API调用失败，已切回本地MPC",
                "risk_note": "云端建议不可用，本步由本地控制接管",
                "confidence": 1.0,
                "fallback": True
            }
            return self.cached_mode

    def get_last_info(self):
        if self.last_response:
            return self.last_response
        return {"reason": "初始化中...", "risk_note": "-", "confidence": 0.0, "fallback": False}


class BiLSTMCloudStrategy(BaseStrategy):
    """校园专网云端 BiLSTM 推理策略

    工程定位
    --------
    本策略对接校园专网内部署的 BiLSTM t+1 冷负荷预测服务，将 39 维多维特征样本
    提交云端推理网关，回收预测负荷、推荐模式、置信度与延迟指标，驱动本地 DDC
    与 SLSQP 寻优进入更前瞻的决策窗口。任何云端通信异常（超时、网络断裂、协议
    错误等）必须被严格捕获，无缝降级至本地 MPC 策略，避免影响白箱物理执行。

    设计原则
    --------
    1) 物理与寻优解耦：本类不直接介入 WhiteBoxEngine 的物理推进与
       ChillerGroupOptimizer 的 SLSQP 求解，仅在 strategy.decide_mode 节点提供模式建议。
    2) 通信故障即降级：云端调用包裹在 try/except 中，失败则调用 fallback 策略
       并通过 engine.log_event 写入事件日志，便于复盘与告警呈现。
    3) UI 可观测：get_last_info 同时暴露云端遥测 (online/predicted_load_kw/
       confidence/latency_ms/endpoint) 与传统 reason/risk_note/confidence/fallback
       字段，前者驱动 BiLSTM 状态面板、后者保持与 AIReportAgent 的向后兼容。
    """

    def __init__(self, fallback_strategy, endpoint='https://campus-bilstm.cloud.local/api/v1/predict',
                 call_every_n=4, fail_rate=0.0, timeout_ms=600):
        # 必须显式传入可独立工作的本地策略作为兜底；缺省 MPCStrategy 在工厂层注入。
        self.fallback = fallback_strategy
        self.endpoint = endpoint
        self.call_every_n = max(1, int(call_every_n))
        self.fail_rate = float(fail_rate)
        self.timeout_ms = int(timeout_ms)

        # 步进缓存与遥测状态
        self.step_counter = 0
        self.cached_mode = None
        self.last_response = None
        self.last_predicted_load_kw = None
        self.last_actual_load_kw = None
        self.last_latency_ms = None
        self.last_confidence = 0.0
        # online 默认 True：未发生过云端调用时视为待启用，由首次 decide_mode 翻转为真实状态。
        self.online = True

    def decide_mode(self, engine, current_factor, dt):
        """对接云端 BiLSTM 推理，回退至本地策略时严格对齐既有契约"""
        self.step_counter += 1

        # 调用频率节流：长序列仿真下复用上一窗口的云端建议，避免对专网造成压力
        if self.cached_mode and (self.step_counter % self.call_every_n != 1):
            return self.cached_mode

        # 解析白箱输入，构造提交云端的 BiLSTM 多维特征
        _, _, target_load, is_night = engine._parse_inputs(current_factor)
        hour = int((engine.sim_time / 60) % 24)
        features = {
            "t_out": current_factor.get("t_out", 33.5),
            "t_in": engine.rc_model.t_in,
            "hour": hour,
            "c_sch": current_factor.get("c_sch", 1.0),
            "c_occ": current_factor.get("c_occ", 1.0),
            "is_night": bool(current_factor.get("is_night", is_night)),
            "current_mode": engine.current_mode,
            "sim_time_min": engine.sim_time,
            "target_load_kw": target_load
        }
        self.last_actual_load_kw = target_load

        try:
            resp = self._call_cloud_bilstm(engine, features)
            self.online = True
            self.cached_mode = resp.get("recommended_mode", "LOW")
            self.last_predicted_load_kw = resp.get("predicted_load_kw")
            self.last_latency_ms = resp.get("latency_ms")
            self.last_confidence = float(resp.get("confidence", 0.0))
            resp["fallback"] = False
            resp["online"] = True
            resp["endpoint"] = self.endpoint
            resp["actual_load_kw"] = target_load
            self.last_response = resp
            return self.cached_mode
        except (TimeoutError, ConnectionError, ValueError, urllib.error.URLError, OSError, Exception) as e:
            # 云端断连：写入事件日志，再行降级，保证 event_log/CSV/UI 三处同步
            self.online = False
            self.last_predicted_load_kw = None
            self.last_latency_ms = None
            self.last_confidence = 0.0
            try:
                engine.log_event('云端BiLSTM失联', '云端 BiLSTM 断开，无缝降级至本地 MPC 策略')
            except Exception:
                pass
            try:
                fallback_mode = self.fallback.decide_mode(engine, current_factor, dt)
            except Exception:
                fallback_mode = "LOW"
            self.cached_mode = fallback_mode
            self.last_response = {
                "reason": "BiLSTM 云端响应超时或异常",
                "risk_note": str(e)[:60] if str(e) else "云端推理通道不可达",
                "confidence": 0.0,
                "fallback": True,
                "online": False,
                "predicted_load_kw": None,
                "latency_ms": None,
                "recommended_mode": fallback_mode,
                "endpoint": self.endpoint,
                "actual_load_kw": target_load
            }
            return fallback_mode

    def get_last_info(self):
        """聚合云端遥测与传统决策信息，供 UI 与 AIReportAgent 共用"""
        if self.last_response is not None:
            info = dict(self.last_response)
        else:
            info = {
                "reason": "BiLSTM 云端策略待启动",
                "risk_note": "尚未发起云端推理调用",
                "confidence": 0.0,
                "fallback": False,
                "recommended_mode": None
            }
        # 始终补齐云端遥测字段，避免 UI 解构 KeyError
        info.setdefault("online", self.online)
        info.setdefault("predicted_load_kw", self.last_predicted_load_kw)
        info.setdefault("confidence", self.last_confidence)
        info.setdefault("latency_ms", self.last_latency_ms)
        info.setdefault("endpoint", self.endpoint)
        info.setdefault("actual_load_kw", self.last_actual_load_kw)
        # 向后兼容：AIReportAgent.generate_report 依赖以下四键
        info.setdefault("reason", "云端 BiLSTM 推理")
        info.setdefault("risk_note", "-")
        info.setdefault("fallback", False)
        return info

    def _call_cloud_bilstm(self, engine, features):
        """模拟校园专网 BiLSTM 推理网关：返回 t+1 预测负荷、置信度与推荐模式

        注意：本实现不发起任何真实 HTTP 调用，仅做确定性模拟以支撑国赛答辩演示与
        断网降级演练；所有数值计算包裹在 try/except 中，数学异常一律上抛触发降级。
        """
        # [竞赛演示版] 以下为确定性模拟实现，工业部署时替换为真实 HTTP/gRPC 调用
        # 模拟器设计目的：1) 架构验证 2) 断网降级演练 3) 答辩演示
        # 真实接入点：self.endpoint（校园专网内网地址）
        # 以 perf_counter 测量端到端耗时，叠加随机模拟延迟以贴近现网表现
        t_start = time.perf_counter()
        simulated_latency = random.uniform(25.0, 90.0)

        # 故障注入：用于断网降级演练，fail_rate=1.0 时确定性触发异常
        if random.random() < self.fail_rate:
            raise TimeoutError('Cloud BiLSTM gateway timeout')

        try:
            target_load = float(features.get("target_load_kw", 0.0) or 0.0)
            hour = int(features.get("hour", 0))
            # t+1 冷负荷 BiLSTM 预测：以基线负荷叠加日周期正弦项与轻量噪声
            seasonal = 1.0 + 0.05 * math.sin(2.0 * math.pi * hour / 24.0)
            noise = random.uniform(-0.015, 0.015) * max(target_load, 1.0)
            predicted_load = max(0.0, target_load * seasonal + noise)

            # 置信度：BiLSTM 推理稳定区间 [0.92, 0.985]
            confidence = round(random.uniform(0.92, 0.985), 4)

            # 依据 engine.th 阈值映射推荐模式，保持与本地规则同源
            th_mid = float(engine.th.get("mid", 2200.0))
            th_high = float(engine.th.get("high", 6000.0))
            if predicted_load >= th_high:
                recommended_mode = "HIGH"
            elif predicted_load >= th_mid:
                recommended_mode = "MID"
            else:
                recommended_mode = "LOW"

            # 夜间工况强制收敛至低负荷模式，避免夜间过度调用中央水系统
            if features.get("is_night", False) and recommended_mode == "HIGH":
                recommended_mode = "MID"
        except Exception as math_err:
            # 数学/类型异常通过抛出触发上层降级路径
            raise ValueError(f"BiLSTM 推理结果解析异常: {math_err}")

        # 真实耗时 + 模拟延迟，单位毫秒
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        latency_ms = round(elapsed_ms + simulated_latency, 1)

        reason = (
            f"云端 BiLSTM 预测 t+1 冷负荷约 {predicted_load:.1f} kW，"
            f"按阈值映射推荐进入【{recommended_mode}】模态以兼顾能效与供冷品质"
        )
        risk_note = "云端推理为辅助决策，最终执行受本地 DDC 安全防线审核"

        return {
            "recommended_mode": recommended_mode,
            "predicted_load_kw": round(predicted_load, 2),
            "confidence": confidence,
            "latency_ms": latency_ms,
            "reason": reason,
            "risk_note": risk_note
        }

# =====================================================================
# 6. 仿真运行器与报告生成
# =====================================================================
class SimulationRunner:
    def __init__(self, engine):
        self.engine = engine

    def execute_sequence(self, scenarios, sequence_plan, strategy,
                         logger=None, building_name="", run_type="sequence"):
        self.engine.reset_state(full=True)
        h_data = []
        times = []
        opt_ps = []
        trad_ps = []
        t_ins = []
        t_outs = []
        switches = []
        s_count = 0
        d_count = 0

        if not sequence_plan:
            return None

        prev_f = scenarios[sequence_plan[0]["scenario"]]
        zone_keys = list(self.engine.zones.keys())

        for plan in sequence_plan:
            target_f = scenarios[plan["scenario"]]
            steps = plan["steps"]
            for i in range(steps):
                ratio = (i + 1) / steps
                interp_zones = {}
                for idx, zk in enumerate(zone_keys):
                    prev_rz = prev_f.get("r_zones", {})
                    tgt_rz = target_f.get("r_zones", {})
                    if isinstance(prev_rz, list):
                        v_prev = prev_rz[idx] if idx < len(prev_rz) else 0.75
                    else:
                        v_prev = prev_rz.get(zk, 0.75)
                    if isinstance(tgt_rz, list):
                        v_target = tgt_rz[idx] if idx < len(tgt_rz) else 0.75
                    else:
                        v_target = tgt_rz.get(zk, 0.75)
                    interp_zones[zk] = v_prev + (v_target - v_prev) * ratio

                interp_f = {
                    "t_out": prev_f["t_out"] + (target_f["t_out"] - prev_f["t_out"]) * ratio,
                    "c_occ": prev_f["c_occ"] + (target_f["c_occ"] - prev_f["c_occ"]) * ratio,
                    "c_sch": target_f["c_sch"],
                    "r_zones": interp_zones,
                    "is_night": target_f["is_night"]
                }

                try:
                    req_mode = strategy.decide_mode(self.engine, interp_f, 15)
                except Exception:
                    req_mode = "LOW"

                ai_info = strategy.get_last_info() if hasattr(strategy, 'get_last_info') else {}
                # 透传 strategy：用于在 execute_step 中观测云端 BiLSTM 的 online 状态并追加降级告警；
                # forced_mode 已显式给定，execute_step 不会再次调用 strategy.decide_mode。
                res = self.engine.execute_step(interp_f, strategy=strategy, forced_mode=req_mode, ai_info=ai_info, dt=15, accumulate_lcc=True)

                h_data.append(res)
                times.append(res['time'] / 60.0)
                opt_ps.append(res['opt_p'])
                trad_ps.append(res['trad_p'])
                t_ins.append(res['t_in'])
                t_outs.append(res['t_out'])
                if res['is_switching']:
                    switches.append(res['time'] / 60.0)
                if res.get('safety_override'):
                    s_count += 1
                if res.get('cooling_satisfaction_val', 1.0) < 0.95 and "待机" not in res.get('cooling_satisfaction_disp', ''):
                    d_count += 1

                if logger:
                    logger.log_step(building_name, plan["scenario"], res, factor=interp_f, engine=self.engine, run_type=run_type)

            prev_f = target_f

        if isinstance(strategy, CloudAIStrategy):
            s_name = getattr(strategy, "p_name", "云端AI")
        elif isinstance(strategy, MPCStrategy):
            s_name = "本地MPC预测控制"
        else:
            s_name = "规则阈值控制"

        return {
            "h_data": h_data, "times": times, "opt_ps": opt_ps, "trad_ps": trad_ps,
            "t_ins": t_ins, "t_outs": t_outs, "switches": switches,
            "lcc_info": self.engine.lcc.evaluate_annual(),
            "total_kwh_saved": self.engine.lcc.total_kwh_saved,
            "safety_override_count": s_count,
            "cooling_deficit_count": d_count,
            "strat_type": s_name
        }


class AIReportAgent:
    def _cn_key(self, key):
        if key in DISPLAY_NAME_MAP:
            return DISPLAY_NAME_MAP[key]
        if key.startswith("BACnet_BO_") and "Valve" in key:
            return f"楼宇自控_阀门开启指令_{key.split('_')[-1]}"
        if key.startswith("BACnet_BI_") and "Valve" in key and key.endswith("_FB"):
            return f"楼宇自控_阀门状态反馈_{key.split('_')[-2]}"
        return key

    def generate_report(self, res, s_name, is_single_step=True):
        alarms_str = ("\n    * ".join(res['cmd'].get('alarms', [])) if res['cmd'].get('alarms')
                      else "状态监测正常，系统无告警")
        shed_str = ("\n   ".join(res['cmd'].get('shedding_seq', [])) if res['cmd'].get('shedding_seq')
                    else "变压器容量正常，未触发减载")
        bacnet_cmd_cn = {self._cn_key(k): v for k, v in res['cmd'].items() if k.startswith("BACnet_")}
        struct_outputs_cn = {self._cn_key(k): v for k, v in res['cmd'].items() if "Actual_" in k or "Delivered_" in k}

        ai_type = res.get('ai_suggested_type', '')
        if ai_type == "CloudAIStrategy":
            strat_type = "云端AI调度协同"
        elif ai_type == "BiLSTMCloudStrategy":
            strat_type = "云端 BiLSTM t+1 冷负荷预测协同"
        elif ai_type == "MPCStrategy":
            strat_type = "本地MPC预测控制"
        elif ai_type == "RuleBasedStrategy":
            strat_type = "本地阈值规则控制"
        else:
            strat_type = ai_type if ai_type else "本地规则"

        ai_info_node = res.get('ai_info', {})
        if ai_info_node.get('fallback', False):
            ai_reason = "API调用失败，已切回本地MPC"
        else:
            ai_reason = ai_info_node.get('reason', '本地白箱规则执行')

        ai_req = MODE_LABELS.get(res.get('ai_requested_mode', 'LOW'), res.get('ai_requested_mode', 'LOW'))
        ai_risk = ai_info_node.get('risk_note', '-')
        is_revised = "是" if res.get('ai_requested_mode') != res.get('combo') else "否"

        s_cfg = res.get("sys_safety_cfg", {})
        trans_limit = s_cfg.get('transformer_capacity_kva', 0) * s_cfg.get('power_factor', 1)
        trans_load = round((res['opt_p'] / trans_limit) * 100, 1) if trans_limit > 0 else 0.0

        rep = (
            f"【工程运行与能效审计报告】 测试工况：{s_name} | 控制策略：{strat_type}\n"
            f"{'='*50}\n"
            f"[1] 热力环境与安全防线\n"
            f"  ▶ 建筑瞬态需求冷负荷: {res['load']} kW\n"
            f"  ▶ 实际交付供冷量: {res['delivered']} kW\n"
            f"  ▶ 供冷品质评定: {res['cooling_satisfaction_disp']}\n"
            f"  ▶ 模拟室内温度: {res['t_in']} ℃ (室外等效温度 {res['t_out']} ℃)\n"
            f"  ▶ 变压器减载保护: {shed_str}\n\n"
            f"[2] 策略发令与 BACnet 执行镜像 (综合 COP={res['active_cop']})\n"
            f"  ▶ 策略推荐模式: {ai_req}\n"
            f"  ▶ 推荐理由: {ai_reason}\n"
            f"  ▶ 潜在风险提示: {ai_risk}\n"
            f"  ▶ 安全层是否修正指令: {is_revised}\n"
            f"  ▶ 最终执行模式: [{MODE_LABELS.get(res['combo'], res['combo'])}] - {res['mech']}\n"
            f"  ▶ 设备实测功率:\n{json.dumps(struct_outputs_cn, ensure_ascii=False, indent=2)}\n"
            f"  ▶ BACnet 寄存器映射:\n{json.dumps(bacnet_cmd_cn, ensure_ascii=False, indent=2)}\n\n"
            f"[3] DDC 安全审计\n"
            f"  ▶ 安全预警记录: {alarms_str}\n"
        )

        c_stat = res.get("chiller_status", {})
        if c_stat.get("running_units", 0) > 0:
            rep += (
                f"  ▶ 冷水机组运行: 投运 {c_stat['running_units']} 台 | PLR {c_stat['plr_percent']}% | COP {c_stat['cop']}\n"
            )

        rep += (
            f"  ▶ 功耗对照: 传统基准 {res['trad_p']} kW vs 优化控制 {res['opt_p']} kW (节能率 {res['rate_disp']})\n"
            f"  ▶ 主变压器负载率: {trans_load}%\n"
            f"  ▶ 底层安全参数: 防喘振下限 {s_cfg.get('central_min_plr',0)*100}% | 变压器容量 {trans_limit} kW | 室温上限 {s_cfg.get('indoor_temp_limit',0)} ℃\n"
        )

        hyd = res.get("hydraulic", {})
        if hyd.get("is_sleep", True):
            hyd_str = "  ▶ 冷冻水系统: VRF 独立运转，中央水系统休眠。\n"
        else:
            branches = hyd.get("branches", [])
            active_branches = [b for b in branches if b.get("flow_m3h", 0) > 0]
            max_br = max(active_branches, key=lambda b: b["branch_total_dp_kpa"]) if active_branches else None
            max_vel = max(active_branches, key=lambda b: b["velocity_ms"]) if active_branches else None
            w_list = [f"{b['zone_name']}({b['warning']})" for b in branches if b["warning"]]
            warnings_str = "、".join(w_list) if w_list else "各支路流速正常"
            hyd_str = (
                f"  ▶ 供回水温度/温差: {hyd['supply_temp_c']} ℃ / {hyd['return_temp_c']} ℃ (ΔT={hyd['delta_t_c']} ℃)\n"
                f"  ▶ 水泵运行: {hyd.get('pump_freq_hz', 0)} Hz ({hyd.get('pump_speed_rpm', 0)} rpm) | 变频开度 {hyd.get('pump_vfd_percent', 0)}%\n"
                f"  ▶ 系统总流量: {hyd['total_flow_m3h']} m³/h | 水泵功率: {hyd['pump_power_kw']} kW | 扬程: {hyd['pump_head_kpa']} kPa / {hyd.get('pump_head_m', 0.0)} m\n"
                f"  ▶ 最不利支路: {max_br['zone_name'] if max_br else '-'} (阻力 {max_br['branch_total_dp_kpa'] if max_br else 0} kPa)\n"
                f"  ▶ 最高流速支路: {max_vel['zone_name'] if max_vel else '-'} (流速 {max_vel['velocity_ms'] if max_vel else 0} m/s)\n"
                f"  ▶ 流速超限告警: {warnings_str}\n\n"
                f"  ▶ 【计算依据说明】\n"
                f"     冷冻水流量按 Q=1.163×G×ΔT 换算；流速按连续性方程 v=Q/A 计算；\n"
                f"     沿程与局部阻力采用速度平方型工程简化模型；支路长度、管径、末端压差\n"
                f"     和阀门开度为可配置假定参数，可由施工图或 BIM 数据导入替换。\n"
            )
        rep += f"\n[4] 冷冻水流程数字孪生数据\n{hyd_str}"

        lcc = res.get("lcc_info")
        if lcc:
            rep += (
                f"\n[5] LCC 全生命周期经济性估算\n"
                f"  ▶ 计价模式: {'分时电价(TOU)' if lcc.get('use_tou') else '平段固定电价'}\n"
                f"  ▶ 仿真时段累计节电量: {res.get('total_kwh_saved', 0.0):.2f} kWh\n"
                f"  ▶ 15年全期财务净现值(NPV): {lcc['NPV']} 万元\n"
                f"  【说明】本估算基于典型日+季节系数推算，非完整 8760 小时审计，仅供参考。"
            )
        return rep

# =====================================================================
# 7. Tkinter GUI
# =====================================================================
class MainPlatformGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("《配置驱动型·智慧建筑空调群控数字孪生平台》")
        self.root.geometry("1320x920")
        self.root.minsize(1180, 760)
        self.last_res = None
        self.history_logger = HistoryLogger()
        self.config_manager = ConfigManager()
        self.engine = WhiteBoxEngine(self.config_manager, list(self.config_manager.building_configs.keys())[0])
        # ─────── 【新增】物理过程量在线展示通道（线程安全） ───────
        # PhysicsSimulationEngine 实例 + queue.Queue 跨线程通道；engine 通过
        # ui_reference.physics_queue.put() 推送，本类主线程通过 process_physics_queue
        # 周期抽干并刷新 UI（Treeview/控制台），仅主线程触碰 Tk。
        self.physics_engine = PhysicsSimulationEngine()
        self.physics_queue = queue.Queue()
        # 反向注入：让 engine 在 execute_step 末尾能拿到本 UI 的队列
        self.engine.ui_reference = self
        # ────────────────────────────────────────────────────────
        self.agent = AIReportAgent()
        self.sim_runner = SimulationRunner(self.engine)
        self._build_ui()
        self.show_welcome_info()
        # 启动主线程轮询（100ms），由 process_physics_queue 抽干 physics_queue 并刷新 UI
        self.root.after(100, self.process_physics_queue)

    def process_physics_queue(self):
        """主线程定时轮询：从 self.physics_queue 抽干所有积压帧，仅渲染最新一帧。

        为什么这样做：
            run_sequence_async 中的 worker 子线程会高频调用 WhiteBoxEngine.execute_step，
            每步都会向 physics_queue 推一帧物理过程量；本方法在 Tk 主线程被
            self.root.after(100, ...) 周期性触发，避免子线程直接操作 Tk 控件。
        """
        try:
            latest = None
            while True:
                try:
                    latest = self.physics_queue.get_nowait()
                except queue.Empty:
                    break
            if latest is not None:
                self._render_physics_state(latest)
        except Exception as exc:
            try:
                log_error("MainPlatformGUI.process_physics_queue", exc)
            except Exception:
                pass
        finally:
            # 不论本次是否取到帧，都重新挂下一次轮询
            try:
                self.root.after(100, self.process_physics_queue)
            except Exception:
                pass

    def _render_physics_state(self, state):
        """把一帧物理过程量渲染到 UI（必须在主线程调用）。

        当前实现：写入控制台日志（self.out 已存在）；后续可扩展为 Treeview / 仪表盘。
        若仓库后续新增 self.tv_physics 等控件，可在此方法补 .insert / .set 即可，
        无需改动队列与轮询基础设施。
        """
        if not isinstance(state, dict):
            return
        try:
            line = (
                "[物理过程] t={t}min 模式={m} | "
                "水泵={pf}Hz 风管余压={dp}Pa EXV={exv}% 最不利环路Δp={wdp}kPa | "
                "冷冻水流量={fw}m³/h 总送风={fa}m³/h 室外={tout}℃"
            ).format(
                t=state.get('sim_time_min', '-'),
                m=state.get('mode', '-'),
                pf=state.get('pump_freq_hz', '-'),
                dp=state.get('duct_static_pressure_pa', '-'),
                exv=state.get('exv_opening_pct', '-'),
                wdp=state.get('worst_loop_dp_kpa', '-'),
                fw=state.get('chw_flow_m3h', '-'),
                fa=state.get('total_air_flow_m3h', '-'),
                tout=state.get('outdoor_temp_c', '-'),
            )
            if hasattr(self, 'out'):
                self.out(line, clear=False)
            # 同步刷新机理监控 Treeview
            try:
                self.update_physics_ui(state)
            except Exception:
                pass
            # ── 更新边缘侧网关性能监控条 ────────────────────────────
            try:
                lat_ai  = state.get("latency_ai")
                lat_opt = state.get("latency_opt")
                mem_mb  = state.get("mem_usage")
                if lat_ai is not None and hasattr(self, "edge_latency_ai_var"):
                    self.edge_latency_ai_var.set(f"{lat_ai:.2f} ms")
                if lat_opt is not None and hasattr(self, "edge_latency_opt_var"):
                    self.edge_latency_opt_var.set(f"{lat_opt:.2f} ms")
                if mem_mb is not None and hasattr(self, "edge_mem_var"):
                    self.edge_mem_var.set(f"{mem_mb:.1f} MB")
                elif mem_mb is None and hasattr(self, "edge_mem_var"):
                    self.edge_mem_var.set("N/A (需安装 psutil)")
            except Exception:
                pass
            # ─────────────────────────────────────────────────────────
        except Exception:
            pass

    def update_physics_ui(self, state):
        """主线程刷新"系统流体力学与热力学过程"Treeview。

        线程模型：
            本方法仅由 process_physics_queue（self.root.after 注册的主线程定时器）触发，
            所有 Tk 操作在主线程完成；子线程仅通过 self.physics_queue.put_nowait(...) 推数。

        行序：
            按"沿管流"逻辑组织 —— 水侧从冷源出水 → 干管流量 → 水泵 → 末端 → 最不利环路压差 → 回水；
            风侧从风机 → 总送风 → 风管余压 → VAV 开度（平均/各区）；
            VRF 段从制冷剂质量流量 → 蒸发温度 → EXV 开度 → PLR；
            环境段：太阳辐射常数（基准）→ 实际辐照度 → 室外温度 → 等效扰动冷负荷。
        """
        if not hasattr(self, "tv_physics") or self.tv_physics is None:
            return
        if not isinstance(state, dict):
            return
        try:
            # 清空旧行
            for item in self.tv_physics.get_children():
                self.tv_physics.delete(item)

            def _fmt(v, nd=2):
                if v is None or v == "":
                    return "--"
                try:
                    return f"{float(v):.{nd}f}"
                except Exception:
                    return str(v)

            # ── 水侧（沿管流：冷源出水 → 总流量 → 水泵 → 末端阀位 → 最不利环路Δp → 回水）──
            water_rows = [
                ("冷机出水（供水）",  "供水温度",       _fmt(state.get("chw_supply_temp_c"), 2), "℃"),
                ("冷冻水干管",        "供水总流量",     _fmt(state.get("chw_flow_m3h"),       1), "m³/h"),
                ("变频水泵",          "运行频率",       _fmt(state.get("pump_freq_hz"),       2), "Hz"),
                ("变频水泵",          "扬程",           _fmt(state.get("pump_head_m"),        2), "m"),
                ("末端二通阀",        "平均阀位",       _fmt(state.get("valve_opening_avg_pct"), 1), "%"),
                ("最不利环路",        "压差 Δp",        _fmt(state.get("worst_loop_dp_kpa"),  2), "kPa"),
                ("冷机回水",          "回水温度",       _fmt(state.get("chw_return_temp_c"),  2), "℃"),
            ]
            for node, param, val, unit in water_rows:
                tags = ("water",)
                # 用户明确点名的 4 个核心物理量加 highlight
                if param in ("运行频率", "压差 Δp"):
                    tags = ("water", "highlight")
                self.tv_physics.insert("", "end",
                    values=("水侧（CHW）", node, param, val, unit), tags=tags)

            # ── 风侧 ──
            air_rows = [
                ("送风机",            "运行频率",       _fmt(state.get("fan_freq_hz"),             2), "Hz"),
                ("空调主风管",        "总送风量",       _fmt(state.get("total_air_flow_m3h"),      1), "m³/h"),
                ("空调主风管",        "余压",           _fmt(state.get("duct_static_pressure_pa"), 1), "Pa"),
            ]
            for node, param, val, unit in air_rows:
                tags = ("air",)
                if param == "余压":
                    tags = ("air", "highlight")
                self.tv_physics.insert("", "end",
                    values=("风侧（VAV）", node, param, val, unit), tags=tags)
            # 各区 VAV 开度（动态展开）
            vav_dict = state.get("vav_openings_pct") or {}
            if isinstance(vav_dict, dict):
                for zk, zv in vav_dict.items():
                    self.tv_physics.insert("", "end",
                        values=("风侧（VAV）", f"VAV-{zk}", "阀位开度", _fmt(zv, 1), "%"),
                        tags=("air",))

            # ── VRF（多联机） ──
            vrf_rows = [
                ("EXV 电子膨胀阀",    "开度",           _fmt(state.get("exv_opening_pct"),          1), "%"),
                ("R410A 制冷剂",      "质量流量",       _fmt(state.get("refrigerant_mass_flow_kgh"), 2), "kg/h"),
                ("蒸发器",            "蒸发温度",       _fmt(state.get("evap_temp_c"),              2), "℃"),
                ("VRF 主机",          "PLR",            _fmt(state.get("vrf_plr"),                  3), "-"),
            ]
            for node, param, val, unit in vrf_rows:
                tags = ("vrf",)
                if param == "开度":
                    tags = ("vrf", "highlight")
                self.tv_physics.insert("", "end",
                    values=("多联机（VRF）", node, param, val, unit), tags=tags)

            # ── 环境扰动 ──
            env_rows = [
                ("太阳常数（基准）",  "I₀",             _fmt(state.get("solar_constant_wm2"),    1), "W/m²"),
                ("落地辐照度",        "G",              _fmt(state.get("solar_irradiance_wm2"),  1), "W/m²"),
                ("室外干球",          "T_out",          _fmt(state.get("outdoor_temp_c"),        2), "℃"),
                ("等效扰动",          "Q_disturb",      _fmt(state.get("disturbance_load_kw"),   2), "kW"),
            ]
            for node, param, val, unit in env_rows:
                self.tv_physics.insert("", "end",
                    values=("环境扰动", node, param, val, unit), tags=("env",))

            # ── 室内热舒适（PMV，ISO 7730）──
            try:
                self.tv_physics.tag_configure("comfort_ok",   background="#E8F8E8", foreground="#15803D",
                                              font=("微软雅黑", 9, "bold"))
                self.tv_physics.tag_configure("comfort_warn", background="#FFE8E8", foreground="#B91C1C",
                                              font=("微软雅黑", 9, "bold"))
                self.tv_physics.tag_configure("comfort_base", background="#FFFCE6")
            except Exception:
                pass

            pmv_val = state.get("PMV_Index")
            try:
                pmv_num = float(pmv_val) if pmv_val is not None else None
            except Exception:
                pmv_num = None

            if pmv_num is None:
                pmv_disp = "--"
                verdict = "--"
                verdict_tag = "comfort_base"
            else:
                pmv_disp = f"{pmv_num:+.2f}"
                if -0.5 <= pmv_num <= 0.5:
                    verdict = "舒适(合规)"
                    verdict_tag = "comfort_ok"
                elif pmv_num > 0.5:
                    verdict = "偏热(超标)"
                    verdict_tag = "comfort_warn"
                else:
                    verdict = "偏冷(超标)"
                    verdict_tag = "comfort_warn"

            self.tv_physics.insert("", "end",
                values=("热舒适（PMV）", "室内空气", "干球温度",
                        _fmt(state.get("indoor_temp_c"), 2), "℃"),
                tags=("comfort_base",))
            self.tv_physics.insert("", "end",
                values=("热舒适（PMV）", "室内空气", "相对湿度",
                        _fmt(state.get("indoor_rh_percent"), 1), "%"),
                tags=("comfort_base",))
            self.tv_physics.insert("", "end",
                values=("热舒适（PMV）", "ISO 7730 PMV", "预测平均投票",
                        pmv_disp, "-"),
                tags=(verdict_tag,))
            self.tv_physics.insert("", "end",
                values=("热舒适（PMV）", "B 类合规区 [-0.5, +0.5]", "判定",
                        verdict, "-"),
                tags=(verdict_tag,))
        except Exception as exc:
            try:
                log_error("MainPlatformGUI.update_physics_ui", exc)
            except Exception:
                pass

    def _build_ui(self):
        """构建更清晰的分区式界面：数据、工况、运行、分析、导出分组，避免按钮横向堆叠。"""
        self.root.configure(bg="#EEF3F7")

        font_title = ("微软雅黑", 15, "bold")
        font_b = ("微软雅黑", 10, "bold")
        font_n = ("微软雅黑", 10)
        font_s = ("微软雅黑", 9)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", padding=3)
        style.configure("Treeview", rowheight=26, font=("微软雅黑", 9))
        style.configure("Treeview.Heading", font=("微软雅黑", 9, "bold"))
        style.configure("TLabelframe.Label", font=font_b)

        def btn(parent, text, command, bg="#3B82F6", fg="white", width=12, **grid_kw):
            b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, font=font_n,
                          activebackground=bg, activeforeground=fg, relief=tk.FLAT,
                          padx=8, pady=5, width=width, cursor="hand2")
            b.grid(**grid_kw)
            return b

        # 顶部标题栏
        header = tk.Frame(self.root, bg="#0F172A", padx=16, pady=10)
        header.pack(fill=tk.X)
        tk.Label(header, text="配置驱动型智慧建筑空调群控数字孪生平台", bg="#0F172A",
                 fg="white", font=font_title).pack(side=tk.LEFT)
        tk.Label(header, text="  通用建筑 / 校园案例 / 测点联动 / 历史数据", bg="#0F172A",
                 fg="#CBD5E1", font=font_s).pack(side=tk.LEFT, padx=12)
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(header, textvariable=self.status_var, bg="#1E293B", fg="#A7F3D0",
                 font=font_s, padx=12, pady=4).pack(side=tk.RIGHT)

        # 主控制区
        control = tk.Frame(self.root, bg="#EEF3F7", padx=12, pady=8)
        control.pack(fill=tk.X)
        for i in range(5):
            control.grid_columnconfigure(i, weight=1, uniform="ctrl")

        fr_data = ttk.LabelFrame(control, text=" ① 数据与台账 ")
        fr_data.grid(row=0, column=0, sticky="nsew", padx=5, pady=4)
        btn(fr_data, "导入建筑", self.import_building_config, bg="#2563EB", width=10, row=0, column=0, padx=4, pady=3, sticky="we")
        btn(fr_data, "导入工况", self.import_scenarios, bg="#2563EB", width=10, row=0, column=1, padx=4, pady=3, sticky="we")
        btn(fr_data, "导入时序", self.import_sequence_plan_ui, bg="#2563EB", width=10, row=1, column=0, padx=4, pady=3, sticky="we")
        btn(fr_data, "导入测点", self.import_point_ledger, bg="#0EA5E9", width=10, row=1, column=1, padx=4, pady=3, sticky="we")
        btn(fr_data, "台账模板", self.export_point_ledger_template, bg="#38BDF8", fg="#082F49", width=10, row=2, column=0, padx=4, pady=3, sticky="we")
        btn(fr_data, "CSV模板", self.export_point_ledger_csv_templates, bg="#BAE6FD", fg="#082F49", width=10, row=2, column=1, padx=4, pady=3, sticky="we")
        for c in range(2): fr_data.grid_columnconfigure(c, weight=1)

        fr_case = ttk.LabelFrame(control, text=" ② 建筑 / 工况 / 策略 ")
        fr_case.grid(row=0, column=1, sticky="nsew", padx=5, pady=4)
        tk.Label(fr_case, text="建筑模板", font=font_s).grid(row=0, column=0, sticky="w", padx=6, pady=(4,0))
        self.cb_bldg = ttk.Combobox(fr_case, values=list(self.config_manager.building_configs.keys()), state="readonly", width=24, font=font_s)
        self.cb_bldg.set(list(self.config_manager.building_configs.keys())[0])
        self.cb_bldg.grid(row=1, column=0, sticky="we", padx=6, pady=2)
        self.cb_bldg.bind("<<ComboboxSelected>>", self.on_building_change)
        tk.Label(fr_case, text="典型工况", font=font_s).grid(row=2, column=0, sticky="w", padx=6, pady=(4,0))
        self.cb_scen = ttk.Combobox(fr_case, values=list(self.config_manager.scenarios.keys()), state="readonly", width=24, font=font_s)
        self.cb_scen.set("03_下午高峰" if "03_下午高峰" in self.config_manager.scenarios else list(self.config_manager.scenarios.keys())[0])
        self.cb_scen.grid(row=3, column=0, sticky="we", padx=6, pady=2)
        tk.Label(fr_case, text="控制策略", font=font_s).grid(row=4, column=0, sticky="w", padx=6, pady=(4,0))
        self.strategy_var = tk.StringVar(value="预测寻优(本地MPC)")
        cb_strat = ttk.Combobox(fr_case, textvariable=self.strategy_var, values=list(STRATEGY_REGISTRY.keys()), state="readonly", width=24, font=font_s)
        cb_strat.grid(row=5, column=0, sticky="we", padx=6, pady=2)
        btn(fr_case, "参数调整", self.edit_current_scenario, bg="#F59E0B", width=10, row=6, column=0, padx=6, pady=6, sticky="we")
        fr_case.grid_columnconfigure(0, weight=1)

        fr_run = ttk.LabelFrame(control, text=" ③ 运行仿真 ")
        fr_run.grid(row=0, column=2, sticky="nsew", padx=5, pady=4)
        self.btn_run = btn(fr_run, "单步仿真", self.run_sim_async, bg="#1D4ED8", width=14, row=0, column=0, padx=5, pady=4, sticky="we")
        self.btn_seq = btn(fr_run, "全天时序仿真", self.run_sequence_async, bg="#15803D", width=14, row=1, column=0, padx=5, pady=4, sticky="we")
        self.btn_comp = btn(fr_run, "策略对比仿真", self.run_comparison_async, bg="#D97706", width=14, row=2, column=0, padx=5, pady=4, sticky="we")
        self.btn_estop = btn(fr_run, "强断急停", self.trigger_estop, bg="#DC2626", width=14, row=3, column=0, padx=5, pady=4, sticky="we")
        btn(fr_run, "重置状态", self.reset_platform, bg="#64748B", width=14, row=4, column=0, padx=5, pady=4, sticky="we")
        fr_run.grid_columnconfigure(0, weight=1)

        fr_view = ttk.LabelFrame(control, text=" ④ 分析与展示 ")
        fr_view.grid(row=0, column=3, sticky="nsew", padx=5, pady=4)
        btn(fr_view, "测点联动分析", self.show_point_linkage_analyzer, bg="#047857", width=12, row=0, column=0, padx=4, pady=3, sticky="we")
        btn(fr_view, "虚拟仪表盘", self.show_virtual_dashboard, bg="#334155", width=12, row=0, column=1, padx=4, pady=3, sticky="we")
        btn(fr_view, "测点梯级表", self.show_flow_checkpoints, bg="#334155", width=12, row=1, column=0, padx=4, pady=3, sticky="we")
        btn(fr_view, "系统拓扑", self.show_system_topology, bg="#0F766E", width=12, row=1, column=1, padx=4, pady=3, sticky="we")
        btn(fr_view, "计算依据", self.show_calculation_basis, bg="#64748B", width=12, row=2, column=0, padx=4, pady=3, sticky="we")
        btn(fr_view, "演示/调试", self.show_demo_tools, bg="#7E22CE", width=12, row=2, column=1, padx=4, pady=3, sticky="we")
        for c in range(2): fr_view.grid_columnconfigure(c, weight=1)

        fr_export = ttk.LabelFrame(control, text=" ⑤ 接口 / 导出 / 日志 ")
        fr_export.grid(row=0, column=4, sticky="nsew", padx=5, pady=4)
        btn(fr_export, "API设置", self.open_api_settings, bg="#7E22CE", width=10, row=0, column=0, padx=4, pady=3, sticky="we")
        btn(fr_export, "API测试", self.test_api, bg="#7E22CE", width=10, row=0, column=1, padx=4, pady=3, sticky="we")
        btn(fr_export, "导出报告", self.export_current_report, bg="#C2410C", width=10, row=1, column=0, padx=4, pady=3, sticky="we")
        btn(fr_export, "导出训练数据", self.export_training_data, bg="#9333EA", width=10, row=1, column=1, padx=4, pady=3, sticky="we")
        btn(fr_export, "事件日志", self.show_logs, bg="#475569", width=10, row=2, column=0, padx=4, pady=3, sticky="we")
        for c in range(2): fr_export.grid_columnconfigure(c, weight=1)

        # AI 决策卡片区
        fr_ai = ttk.LabelFrame(self.root, text=" AI 决策看板 ")
        fr_ai.pack(fill=tk.X, padx=15, pady=(2, 6))
        self.ai_mode_var = tk.StringVar(value="-")
        self.ai_reason_var = tk.StringVar(value="-")
        self.ai_risk_var = tk.StringVar(value="-")
        self.ai_conf_var = tk.StringVar(value="-")
        self.ai_source_var = tk.StringVar(value="-")
        self.ai_fallback_var = tk.StringVar(value="-")

        ai_items = [
            ("推荐模式", self.ai_mode_var, "#1D4ED8"),
            ("置信度", self.ai_conf_var, "#15803D"),
            ("策略来源", self.ai_source_var, "#7E22CE"),
            ("是否降级", self.ai_fallback_var, "#C2410C"),
        ]
        for i, (lab, var, color) in enumerate(ai_items):
            card = tk.Frame(fr_ai, bg="white", bd=1, relief=tk.SOLID, padx=10, pady=5)
            card.grid(row=0, column=i, sticky="nsew", padx=5, pady=5)
            tk.Label(card, text=lab, bg="white", fg="#64748B", font=font_s).pack(anchor="w")
            tk.Label(card, textvariable=var, bg="white", fg=color, font=("微软雅黑", 11, "bold"), wraplength=210).pack(anchor="w")
            fr_ai.grid_columnconfigure(i, weight=1)
        tk.Label(fr_ai, text="推荐理由：", font=font_b).grid(row=1, column=0, sticky="nw", padx=8, pady=2)
        tk.Label(fr_ai, textvariable=self.ai_reason_var, font=font_s, wraplength=760, justify=tk.LEFT).grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        tk.Label(fr_ai, text="风险提示：", font=font_b).grid(row=2, column=0, sticky="nw", padx=8, pady=2)
        tk.Label(fr_ai, textvariable=self.ai_risk_var, font=font_s, fg="#B91C1C", wraplength=760, justify=tk.LEFT).grid(row=2, column=1, columnspan=3, sticky="w", padx=4)

        # BiLSTM 云端引擎状态面板：实时呈现校园专网 BiLSTM 推理通道的连接、预测、置信度与延迟
        fr_bilstm = ttk.LabelFrame(self.root, text=" BiLSTM 云端引擎状态面板 ")
        fr_bilstm.pack(fill=tk.X, padx=15, pady=(2, 6))
        self.bilstm_load_var = tk.StringVar(value="预测 t+1: --\n实际仿真: --")
        self.bilstm_conf_var = tk.StringVar(value="--")
        self.bilstm_latency_var = tk.StringVar(value="--")

        # 卡片 1：连接状态（使用 tk.Label 直存引用，便于运行时翻转 fg 颜色）
        card_status = tk.Frame(fr_bilstm, bg="white", bd=1, relief=tk.SOLID, padx=10, pady=5)
        card_status.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        tk.Label(card_status, text="BiLSTM 云端连接", bg="white", fg="#64748B", font=font_s).pack(anchor="w")
        self.bilstm_status_label = tk.Label(card_status, text="● 待启动", bg="white", fg="#64748B",
                                            font=("微软雅黑", 11, "bold"), wraplength=210, justify=tk.LEFT, anchor="w")
        self.bilstm_status_label.pack(anchor="w", fill=tk.X)

        # 卡片 2：预测负荷 vs 实际仿真负荷
        card_load = tk.Frame(fr_bilstm, bg="white", bd=1, relief=tk.SOLID, padx=10, pady=5)
        card_load.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        tk.Label(card_load, text="BiLSTM 预测负荷 vs 实际", bg="white", fg="#64748B", font=font_s).pack(anchor="w")
        tk.Label(card_load, textvariable=self.bilstm_load_var, bg="white", fg="#1D4ED8",
                 font=("微软雅黑", 11, "bold"), wraplength=240, justify=tk.LEFT, anchor="w").pack(anchor="w", fill=tk.X)

        # 卡片 3：预测置信度
        card_conf = tk.Frame(fr_bilstm, bg="white", bd=1, relief=tk.SOLID, padx=10, pady=5)
        card_conf.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        tk.Label(card_conf, text="预测置信度", bg="white", fg="#64748B", font=font_s).pack(anchor="w")
        tk.Label(card_conf, textvariable=self.bilstm_conf_var, bg="white", fg="#15803D",
                 font=("微软雅黑", 11, "bold"), wraplength=210).pack(anchor="w")

        # 卡片 4：API 响应延迟
        card_lat = tk.Frame(fr_bilstm, bg="white", bd=1, relief=tk.SOLID, padx=10, pady=5)
        card_lat.grid(row=0, column=3, sticky="nsew", padx=5, pady=5)
        tk.Label(card_lat, text="API 响应延迟", bg="white", fg="#64748B", font=font_s).pack(anchor="w")
        tk.Label(card_lat, textvariable=self.bilstm_latency_var, bg="white", fg="#7E22CE",
                 font=("微软雅黑", 11, "bold"), wraplength=210).pack(anchor="w")

        for i in range(4):
            fr_bilstm.grid_columnconfigure(i, weight=1)

        # ─────── 边缘侧网关性能监控面板 ─────────────────────────────
        # 实时展示 BiLSTM 推理延迟、SLSQP 寻优耗时与进程内存占用，
        # 数据来源：WhiteBoxEngine.execute_step 埋点 → physics_queue → 主线程解包。
        fr_edge = ttk.LabelFrame(self.root, text=" ⚡ 边缘侧网关性能监控 ")
        fr_edge.pack(fill=tk.X, padx=15, pady=(0, 4))

        self.edge_latency_ai_var  = tk.StringVar(value="-- ms")
        self.edge_latency_opt_var = tk.StringVar(value="-- ms")
        self.edge_mem_var         = tk.StringVar(value="-- MB")

        _edge_items = [
            ("BiLSTM 推理延迟",  self.edge_latency_ai_var,  "#1D4ED8"),
            ("寻优决策耗时",     self.edge_latency_opt_var, "#15803D"),
            ("边缘网关内存占用", self.edge_mem_var,          "#7E22CE"),
        ]
        for _i, (_label, _var, _color) in enumerate(_edge_items):
            _card = tk.Frame(fr_edge, bg="white", bd=1, relief=tk.SOLID, padx=10, pady=4)
            _card.grid(row=0, column=_i, sticky="nsew", padx=5, pady=4)
            tk.Label(_card, text=_label, bg="white", fg="#64748B", font=font_s).pack(anchor="w")
            tk.Label(_card, textvariable=_var, bg="white", fg=_color,
                     font=("微软雅黑", 11, "bold"), wraplength=220).pack(anchor="w")
            fr_edge.grid_columnconfigure(_i, weight=1)
        # ─────────────────────────────────────────────────────────────

        # 内容区：上方水力表，下方控制台输出，可拖动分隔
        paned = tk.PanedWindow(self.root, orient=tk.VERTICAL, sashrelief=tk.RAISED, bg="#CBD5E1")
        paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=4)

        self.fr_hyd = ttk.LabelFrame(paned, text=" 冷冻水末端数字孪生表 ")
        self.hyd_cols = ("支路名称", "末端类型", "供冷(kW)", "估算风量(m³/h)", "水流量(m³/h)",
                         "阀门开度(%)", "管路阻力(kPa)", "送风温度(℃)", "回风温度(℃)", "数据溯源")
        self.tv_hyd = ttk.Treeview(self.fr_hyd, columns=self.hyd_cols, show='headings', height=5)
        self.tv_hyd.tag_configure('alert', foreground='red', font=("微软雅黑", 9, "bold"))
        self.tv_hyd.tag_configure('sleep', foreground='gray')
        for c in self.hyd_cols:
            self.tv_hyd.heading(c, text=c)
            w = 135 if c in ("支路名称", "末端类型", "数据溯源") else 105
            self.tv_hyd.column(c, width=w, anchor="center")
        yscroll = ttk.Scrollbar(self.fr_hyd, orient="vertical", command=self.tv_hyd.yview)
        xscroll = ttk.Scrollbar(self.fr_hyd, orient="horizontal", command=self.tv_hyd.xview)
        self.tv_hyd.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tv_hyd.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.fr_hyd.grid_rowconfigure(0, weight=1)
        self.fr_hyd.grid_columnconfigure(0, weight=1)
        paned.add(self.fr_hyd, minsize=150)

        # ─────── ⑦ 系统流体力学与热力学过程（机理监控面板） ───────
        # 实时展示 PhysicsSimulationEngine.simulate_all 反算的水/风/VRF/环境过程量，
        # 行序按"沿管流"顺序排布：冷源 → 干管 → 末端 → 回水 / 风源 → 干管 → 末端 / VRF / 环境。
        fr_physics = ttk.LabelFrame(paned, text=" ⑦ 系统流体力学与热力学过程 ")

        cols_phy = ("子系统", "节点", "参数", "数值", "单位")
        self.tv_physics = ttk.Treeview(fr_physics, columns=cols_phy, show="headings", height=14)
        for col, w in zip(cols_phy, (110, 240, 110, 130, 70)):
            self.tv_physics.heading(col, text=col)
            self.tv_physics.column(col, width=w, anchor="center")
        # 颜色 tag：每个子系统一个底色，便于区分管路段
        self.tv_physics.tag_configure("water", background="#E6F4FF")  # 水侧浅蓝
        self.tv_physics.tag_configure("air",   background="#F0FFE6")  # 风侧浅绿
        self.tv_physics.tag_configure("vrf",   background="#FFF7E6")  # VRF 浅橙
        self.tv_physics.tag_configure("env",   background="#F5F0FF")  # 环境浅紫
        self.tv_physics.tag_configure("highlight", foreground="#B22222", font=("微软雅黑", 9, "bold"))
        # 滚动条
        sb_phy = ttk.Scrollbar(fr_physics, orient="vertical", command=self.tv_physics.yview)
        self.tv_physics.configure(yscrollcommand=sb_phy.set)
        self.tv_physics.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb_phy.pack(side="right", fill="y", padx=(0, 4), pady=4)
        paned.add(fr_physics, minsize=200)
        # ─────────────────────────────────────────────────────────

        fr_out = ttk.LabelFrame(paned, text=" 运行报告 / 控制台输出 ")
        self.txt_out = scrolledtext.ScrolledText(fr_out, font=("Consolas", 10), bg="#0F172A", fg="#A7F3D0", insertbackground="white", height=12)
        self.txt_out.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        paned.add(fr_out, minsize=220)

        note = (
            "【工程声明】本系统为仿真运行数据采集平台，不宣称接入现场真实传感器，不宣称完成真实项目 AI 训练。"
            " 水力测点、阻力及泵阀工况为仿真测点，可由施工图、BIM 或 BAS 点位替换。"
        )
        self.note_var = tk.StringVar(value=note)
        tk.Label(self.root, textvariable=self.note_var, fg="#B91C1C", bg="#FEF2F2",
                 font=("微软雅黑", 9, "bold"), justify=tk.LEFT, anchor="w", padx=12, pady=6).pack(fill=tk.X, padx=15, pady=(0, 5))

    def out(self, text, clear=True):
        if clear:
            self.txt_out.delete(1.0, tk.END)
        self.txt_out.insert(tk.END, str(text) + "\n")
        self.txt_out.see(tk.END)
        if hasattr(self, "status_var"):
            preview = str(text).strip().split("\n")[0][:42] if str(text).strip() else "就绪"
            self.status_var.set(preview)
        self.root.update_idletasks()

    def set_buttons_state(self, state):
        self.btn_run.config(state=state)
        self.btn_seq.config(state=state)
        self.btn_comp.config(state=state)
        if hasattr(self, "status_var"):
            self.status_var.set("运行中..." if state == "disabled" else "就绪")

    def _get_current_strategy(self, is_sequence=False):
        cfg_entry = STRATEGY_REGISTRY.get(self.strategy_var.get(), STRATEGY_REGISTRY["预测寻优(本地MPC)"])
        if cfg_entry["type"] == "local":
            if cfg_entry["provider"] == "local_rule":
                return RuleBasedStrategy()
            else:
                return MPCStrategy()
        else:
            # 校园专网 BiLSTM t+1 冷负荷预测策略：以本地 MPC 为兜底，长序列下节流调用频率
            if cfg_entry["provider"] == "bilstm":
                return BiLSTMCloudStrategy(
                    fallback_strategy=MPCStrategy(),
                    call_every_n=4 if is_sequence else 1
                )
            return CloudAIStrategy(
                cfg_entry["provider"],
                self.config_manager.api_config,
                fallback_strategy=MPCStrategy(),
                call_every_n=4 if is_sequence else 1
            )

    def _update_bilstm_panel(self, ai_info, res):
        if not hasattr(self, 'bilstm_status_label'):
            return  # GUI 尚未初始化完成
        """刷新 BiLSTM 云端引擎状态面板：根据当前策略判定云端在线/离线/未启用三态

        Parameters
        ----------
        ai_info : dict
            策略 get_last_info() 输出，含 online / predicted_load_kw / confidence /
            latency_ms / fallback 等字段；仅在 BiLSTM 策略下做完整渲染。
        res : dict
            engine.execute_step 返回的当步结果，用于读取实际仿真负荷以与预测负荷对照。
        """
        # 通过 STRATEGY_REGISTRY 反查当前激活策略；非 BiLSTM 时面板进入 inert 状态，避免误读
        cfg_entry = STRATEGY_REGISTRY.get(self.strategy_var.get(), {})
        is_bilstm = (cfg_entry.get("provider") == "bilstm")

        if not is_bilstm:
            # 当前策略非 BiLSTM 云端预测：清晰标注未启用，避免遗留陈旧数据误导操作员
            try:
                self.bilstm_status_label.config(text="● 未启用 (当前为本地策略)", fg="#64748B")
            except Exception:
                pass
            self.bilstm_load_var.set("预测 t+1: --\n实际仿真: --")
            self.bilstm_conf_var.set("--")
            self.bilstm_latency_var.set("--")
            return

        ai_info = ai_info or {}
        # online 字段优先，缺省时退化为 not fallback
        online = ai_info.get("online", not ai_info.get("fallback", False))
        predicted = ai_info.get("predicted_load_kw")
        confidence = ai_info.get("confidence", 0.0) or 0.0
        latency = ai_info.get("latency_ms")
        actual = (res or {}).get("load")
        if actual is None:
            actual = ai_info.get("actual_load_kw")

        # 状态色翻转：在线绿 / 离线红
        try:
            if online:
                self.bilstm_status_label.config(text="● 云端在线", fg="#16A34A")
            else:
                self.bilstm_status_label.config(text="● 云端离线，已降级至本地 MPC", fg="#DC2626")
        except Exception:
            pass

        # 预测负荷 vs 实际仿真负荷
        pred_str = f"{predicted:.1f} kW" if isinstance(predicted, (int, float)) else "--"
        act_str = f"{actual:.1f} kW" if isinstance(actual, (int, float)) else "--"
        self.bilstm_load_var.set(f"预测 t+1: {pred_str}\n实际仿真: {act_str}")

        # 置信度百分比
        try:
            self.bilstm_conf_var.set(f"{float(confidence) * 100:.1f}%")
        except Exception:
            self.bilstm_conf_var.set("--")

        # API 响应延迟
        if isinstance(latency, (int, float)):
            self.bilstm_latency_var.set(f"{latency:.0f} ms")
        else:
            self.bilstm_latency_var.set("--")

    def on_building_change(self, event=None):
        b_key = self.cb_bldg.get()
        self.engine.load_building(b_key)
        self.reset_platform()
        self.out(f"已加载建筑物理模型: 【{b_key}】", clear=True)

    def show_virtual_dashboard(self):
        if not self.last_res:
            messagebox.showwarning("无数据", "请先执行单步仿真。")
            return
        top = tk.Toplevel(self.root)
        top.title("机房中心虚拟仪表盘")
        top.geometry("620x360")
        top.configure(bg="#2C3E50")
        hyd = self.last_res.get("hydraulic", {})

        def make_dash(parent, r, c, title, val, unit, color):
            f = tk.Frame(parent, bg="#34495E", bd=2, relief=tk.RIDGE)
            f.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            tk.Label(f, text=title, font=("微软雅黑", 10), bg="#34495E", fg="white").pack(pady=5)
            tk.Label(f, text=str(val), font=("Arial", 20, "bold"), bg="#34495E", fg=color).pack()
            tk.Label(f, text=unit, font=("微软雅黑", 9), bg="#34495E", fg="gray").pack(pady=5)

        make_dash(top, 0, 0, "冷冻水出水温度", hyd.get("supply_temp_c", "--"), "℃", "#3498DB")
        make_dash(top, 0, 1, "回水干管温度", hyd.get("return_temp_c", "--"), "℃", "#E74C3C")
        make_dash(top, 0, 2, "系统循环总流量", hyd.get("total_flow_m3h", "--"), "m³/h", "#2ECC71")
        make_dash(top, 0, 3, "水泵运行频率", hyd.get("pump_freq_hz", "--"), "Hz", "#F1C40F")
        make_dash(top, 1, 0, "水泵扬程", hyd.get("pump_head_m", "--"), "m", "#9B59B6")
        make_dash(top, 1, 1, "变频泵轴功率", hyd.get("pump_power_kw", "--"), "kW", "#E67E22")
        limit_kw = self.engine.sys_config['safety']['transformer_capacity_kva'] * self.engine.sys_config['safety']['power_factor']
        opt_p = self.last_res.get('opt_p', 0)
        trans_load = round((opt_p / limit_kw) * 100, 1) if limit_kw > 0 else 0
        make_dash(top, 1, 2, "主变压器负载率", trans_load, "%", "#E74C3C" if opt_p > limit_kw else "#2ECC71")
        sat = min(100.0, round(self.last_res.get('cooling_satisfaction_val', 1.0) * 100, 1))
        make_dash(top, 1, 3, "末端供冷满足率", sat, "%", "#1ABC9C")

    def show_flow_checkpoints(self):
        if not self.last_res:
            messagebox.showwarning("无数据", "请先执行单步仿真。")
            return
        top = tk.Toplevel(self.root)
        top.title("冷冻水梯级虚拟测点仪表册")
        top.geometry("750x300")
        cols = ("虚拟物理节点", "流体温度(℃)", "管网表压(kPa)", "流经流量(m³/h)", "节点说明")
        tv = ttk.Treeview(top, columns=cols, show='headings', height=6)
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=130, anchor="center")
        tv.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        hyd = self.last_res.get("hydraulic", {})
        if hyd.get("is_sleep", True):
            tv.insert("", "end", values=("全系统测点", "--", "--", "--", "VRF独立运转，中央冷冻水侧休眠"))
        else:
            cps = hyd.get("checkpoints", {})
            rows = [
                ("冷水机组蒸发器出口", "chiller_out", "供水总管源头"),
                ("主循环加压水泵出口", "pump_out", "二次加压后"),
                ("大系统供水侧分水器", "distributor", "向各支路分配"),
                ("最不利末端盘管入口", "term_in", "调节阀前测点"),
                ("最不利末端盘管出口", "term_out", "完成释冷"),
                ("回流总管及机组入口", "return_main", "热力学闭环")
            ]
            for label, key, desc in rows:
                cp = cps.get(key, {})
                tv.insert("", "end", values=(label, cp.get("T", "--"), cp.get("P", "--"), cp.get("F", "--"), desc))


    def show_point_linkage_analyzer(self):
        top = tk.Toplevel(self.root)
        top.title("房间/区域测点联动分析")
        top.geometry("980x620")

        fr_ctrl = tk.LabelFrame(top, text=" 测点选择与参数改写 ", font=("微软雅黑", 10, "bold"), padx=10, pady=8)
        fr_ctrl.pack(fill=tk.X, padx=10, pady=8)

        tk.Label(fr_ctrl, text="区域/房间:").grid(row=0, column=0, padx=5, pady=4, sticky="e")
        model_preview = TerminalPointLinkageModel(self.engine.zone_specs, self.engine.sys_config, self.last_res, self.config_manager.point_ledger)
        target_values = model_preview.available_targets()
        zone_var = tk.StringVar(value=target_values[0] if target_values else "")
        cb_zone = ttk.Combobox(fr_ctrl, textvariable=zone_var, values=target_values, state="readonly", width=26)
        cb_zone.grid(row=0, column=1, padx=5, pady=4)

        tk.Label(fr_ctrl, text="系统类型:").grid(row=0, column=2, padx=5, pady=4, sticky="e")
        sys_var = tk.StringVar(value="全部")
        cb_sys = ttk.Combobox(fr_ctrl, textvariable=sys_var, values=["全部", "冷冻水系统", "风系统", "冷却水系统", "机组影响", "BAS/DDC点位"], state="readonly", width=14)
        cb_sys.grid(row=0, column=3, padx=5, pady=4)
        writeback_var = tk.BooleanVar(value=False)
        tk.Checkbutton(fr_ctrl, text="写回当前台账/配置", variable=writeback_var).grid(row=0, column=4, columnspan=2, padx=8, sticky="w")

        input_defs = [
            ("冷冻水流量", "chilled_water_flow_m3h", "m³/h"),
            ("送风量", "airflow_m3h", "m³/h"),
            ("风管截面积", "air_duct_area_m2", "m²"),
            ("冷却水流量", "cooling_water_flow_m3h", "m³/h"),
            ("冷却水供水温度", "cooling_water_supply_temp", "℃"),
            ("冷却水回水温度", "cooling_water_return_temp", "℃")
        ]
        entry_map = {}
        for idx, (label, key, unit) in enumerate(input_defs):
            r = 1 + idx // 3
            c = (idx % 3) * 3
            tk.Label(fr_ctrl, text=f"{label}:").grid(row=r, column=c, padx=5, pady=4, sticky="e")
            e = tk.Entry(fr_ctrl, width=12)
            e.grid(row=r, column=c+1, padx=3, pady=4)
            tk.Label(fr_ctrl, text=unit, fg="gray").grid(row=r, column=c+2, padx=2, pady=4, sticky="w")
            entry_map[key] = e

        cols = ("测点类别", "测点名称", "数值", "单位", "联动说明")
        tv = ttk.Treeview(top, columns=cols, show="headings", height=18)
        tv.tag_configure('warn', foreground='red', font=("微软雅黑", 9, "bold"))
        tv.tag_configure('impact', foreground='#8E44AD')
        for c in cols:
            tv.heading(c, text=c)
            if c == "联动说明":
                tv.column(c, width=380, anchor="w")
            elif c == "测点名称":
                tv.column(c, width=160, anchor="center")
            else:
                tv.column(c, width=110, anchor="center")
        tv.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        note = (
            "说明：本模块为房间/区域末端测点联动仿真。风速、流速、阻力、流量、冷量和机组功率"
            "均基于工程公式联动计算。当前数据为可配置仿真测点，不等同于现场传感器实测值；"
            "后续可由压力表、流量计、温度传感器、BAS点位或BIM管网模型替换。"
        )
        tk.Label(top, text=note, fg="#C0392B", font=("微软雅黑", 9, "bold"), wraplength=930, justify=tk.LEFT).pack(anchor="w", padx=14, pady=6)

        def parse_overrides():
            overrides = {}
            for key, entry in entry_map.items():
                raw = entry.get().strip()
                if raw:
                    try:
                        overrides[key] = float(raw)
                    except ValueError:
                        messagebox.showwarning("输入无效", f"参数 {key} 必须为数字。", parent=top)
                        return None
            return overrides

        def apply_overrides_to_config(target_name, overrides):
            if not overrides:
                return False
            model = TerminalPointLinkageModel(self.engine.zone_specs, self.engine.sys_config, self.last_res, self.config_manager.point_ledger)
            resolved_zone, room_id, room_cfg = model._resolve_target(target_name)
            changed = False
            # 写回区域默认参数
            if resolved_zone in self.engine.zone_specs:
                z_cfg = self.engine.zone_specs[resolved_zone]
                b_zone = self.engine.b_cfg.get("zones", {}).get(resolved_zone, {})
                if isinstance(b_zone, dict):
                    if "air_duct_area_m2" in overrides:
                        z_cfg["air_duct_area_m2"] = overrides["air_duct_area_m2"]; b_zone["air_duct_area_m2"] = overrides["air_duct_area_m2"]; changed = True
                    if "airflow_m3h" in overrides:
                        z_cfg["design_airflow_m3h"] = overrides["airflow_m3h"]; b_zone["design_airflow_m3h"] = overrides["airflow_m3h"]; changed = True
                    if "chilled_water_flow_m3h" in overrides:
                        # 通过流量反算设计冷量，供下一轮台账分析使用，不强制改主仿真历史状态
                        z_cfg["design_load_kw"] = max(0.1, 1.163 * overrides["chilled_water_flow_m3h"] * 5.0); b_zone["design_load_kw"] = z_cfg["design_load_kw"]; changed = True
            # 写回房间/支路台账
            ledger = self.config_manager.point_ledger
            if room_id and room_id in ledger.get("rooms", {}):
                if "airflow_m3h" in overrides:
                    ledger["rooms"][room_id]["design_airflow_m3h"] = overrides["airflow_m3h"]; changed = True
                if "chilled_water_flow_m3h" in overrides:
                    ledger["rooms"][room_id]["design_load_kw"] = max(0.1, 1.163 * overrides["chilled_water_flow_m3h"] * 5.0); changed = True
            for bid, br in ledger.get("chw_branches", {}).items():
                if br.get("room_id") == room_id or br.get("zone_id") == model._zone_id_by_name(resolved_zone):
                    if "chilled_water_flow_m3h" in overrides:
                        br["design_flow_m3h"] = overrides["chilled_water_flow_m3h"]; changed = True
            for bid, br in ledger.get("air_branches", {}).items():
                if br.get("room_id") == room_id or br.get("zone_id") == model._zone_id_by_name(resolved_zone):
                    if "air_duct_area_m2" in overrides:
                        br["duct_area_m2"] = overrides["air_duct_area_m2"]; changed = True
                    if "airflow_m3h" in overrides:
                        br["design_airflow_m3h"] = overrides["airflow_m3h"]; changed = True
            if changed:
                self.engine.hydraulic_model = HydraulicNetworkModel(self.engine.zone_specs, self.engine.sys_config)
            return changed

        def refresh_results():
            overrides = parse_overrides()
            if overrides is None:
                return
            if writeback_var.get():
                try:
                    changed = apply_overrides_to_config(zone_var.get(), overrides)
                    if changed:
                        messagebox.showinfo("已写回", "参数已写回当前台账/配置。请重新运行单步或全天仿真后查看主系统变化。", parent=top)
                except Exception as e:
                    log_error("show_point_linkage_analyzer.apply_overrides", e)
                    messagebox.showerror("写回失败", str(e), parent=top)
                    return
            for item in tv.get_children():
                tv.delete(item)
            zone_name = zone_var.get()
            if not zone_name:
                return
            model = TerminalPointLinkageModel(self.engine.zone_specs, self.engine.sys_config, self.last_res, self.config_manager.point_ledger)
            rows = model.analyze_zone(zone_name, overrides=overrides)
            sys_filter = sys_var.get()
            category_map = {
                "冷冻水系统": "冷冻水管",
                "风系统": "风管",
                "冷却水系统": "冷却水管",
                "机组影响": "机组影响",
                "BAS/DDC点位": "BAS/DDC点位"
            }
            target_category = category_map.get(sys_filter)
            for row in rows:
                if target_category and row["category"] != target_category:
                    continue
                tag = ()
                if row["category"] == "机组影响":
                    tag = ('impact',)
                if "告警" in row["name"] or "阻力" in row["name"] and isinstance(row["value"], (int, float)) and row["value"] > 200:
                    tag = ('warn',)
                tv.insert("", "end", values=(row["category"], row["name"], row["value"], row["unit"], row["note"]), tags=tag)

        def fill_defaults_for_zone(event=None):
            for e in entry_map.values():
                e.delete(0, tk.END)
            zone_name = zone_var.get()
            if not zone_name:
                return
            model = TerminalPointLinkageModel(self.engine.zone_specs, self.engine.sys_config, self.last_res, self.config_manager.point_ledger)
            resolved_zone, room_id, room_cfg = model._resolve_target(zone_name)
            z_cfg = self.engine.zone_specs.get(resolved_zone, {})
            design_kw = float((room_cfg or {}).get("design_load_kw", z_cfg.get("design_load_kw", 1000.0)))
            default_airflow = float((room_cfg or {}).get("design_airflow_m3h", z_cfg.get("design_airflow_m3h", design_kw * 250.0))) * 0.7
            default_chw = design_kw * 0.7 / (1.163 * 5.0)
            entry_map["chilled_water_flow_m3h"].insert(0, f"{default_chw:.2f}")
            entry_map["airflow_m3h"].insert(0, f"{default_airflow:.0f}")
            entry_map["air_duct_area_m2"].insert(0, str(z_cfg.get("air_duct_area_m2", 1.2)))
            entry_map["cooling_water_flow_m3h"].insert(0, f"{default_chw*1.2:.2f}")
            entry_map["cooling_water_supply_temp"].insert(0, "32")
            entry_map["cooling_water_return_temp"].insert(0, "37")
            refresh_results()

        cb_zone.bind("<<ComboboxSelected>>", fill_defaults_for_zone)
        cb_sys.bind("<<ComboboxSelected>>", lambda event=None: refresh_results())
        tk.Button(fr_ctrl, text="联动计算", bg="#117864", fg="white", font=("微软雅黑", 10, "bold"), command=refresh_results).grid(row=3, column=0, columnspan=3, sticky="we", padx=5, pady=8)
        tk.Button(fr_ctrl, text="恢复默认测点", bg="#7F8C8D", fg="white", font=("微软雅黑", 10), command=fill_defaults_for_zone).grid(row=3, column=3, columnspan=3, sticky="we", padx=5, pady=8)

        fill_defaults_for_zone()

    def show_demo_tools(self):
        top = tk.Toplevel(self.root)
        top.title("演示与调试工具箱")
        top.geometry("450x320")
        tk.Label(top, text="测试边界与异常工况", font=("微软雅黑", 10, "bold"), fg="#8E44AD", pady=10).pack()

        tk.Button(top, text="生成运行结论说明", bg="#16A085", fg="white", font=("微软雅黑", 10), width=25, command=self.generate_defense_summary).pack(pady=5)
        tk.Button(top, text="控制策略说明", bg="#34495E", fg="white", font=("微软雅黑", 10), width=25, command=self.show_judge_script).pack(pady=5)

        fr_test = tk.LabelFrame(top, text="极限工况测试", font=("微软雅黑", 10, "bold"), padx=10, pady=10)
        fr_test.pack(fill=tk.X, padx=20, pady=10)

        self.abnormal_var = tk.StringVar(value="常规标准工况")
        cb_abnormal = ttk.Combobox(fr_test, textvariable=self.abnormal_var,
                                   values=["常规标准工况", "室外极端高温(42℃)", "变压器容量限载", "低负荷防喘振测试", "多联机容量受限测试"],
                                   state="readonly", width=20)
        cb_abnormal.pack(side=tk.LEFT, padx=10)
        tk.Button(fr_test, text="注入测试工况", bg="#E74C3C", fg="white",
                  command=lambda: self.trigger_abnormal_test(top)).pack(side=tk.LEFT, padx=10)

    def show_judge_script(self):
        script = (
            "【控制策略与计算依据说明】\n\n"
            "1. 建筑冷量需求由区域动态 RC 负荷模型产生；冷冻水流量遵循水系统能量守恒公式\n"
            "   (Q=1.163×G×ΔT) 计算；管网内流体流速依据连续性方程实时计算。\n\n"
            "2. 管路沿程阻力和局部阻力采用速度平方型工程简化模型。支路几何长度、标定管径、\n"
            "   末端压差与阀门开度均作为可配置工程假定参数。\n\n"
            "3. 历史运行数据记录器（HistoryLogger）沉淀多维时序特征，支持后续离线训练负荷\n"
            "   预测、策略推荐及管网异常识别模型。\n\n"
            "4. 当前水力测点数据为仿真计算值，计算逻辑自洽。实施阶段可由施工图管径表、\n"
            "   BIM 管网模型或现场传感器实测数据接管替换。"
        )
        top = tk.Toplevel(self.root)
        top.title("控制策略与计算依据说明")
        top.geometry("650x380")
        txt = scrolledtext.ScrolledText(top, font=("微软雅黑", 11), padx=15, pady=15, bg="#F9EBEA")
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert(tk.END, script)
        txt.config(state="disabled")

    def trigger_abnormal_test(self, parent_top):
        ab_type = self.abnormal_var.get()
        s_name = self.cb_scen.get()
        base = self.config_manager.scenarios.get(s_name, DEFAULT_SCENARIOS["03_下午高峰"])
        factor = base.copy()
        factor["r_zones"] = base.get("r_zones", {}).copy() if isinstance(base.get("r_zones"), dict) else list(base.get("r_zones", []))

        old_kva = self.engine.sys_config['safety']['transformer_capacity_kva']
        old_vrf = self.engine.sys_config['equipment']['capacity_vrf_kw']

        if ab_type == "室外极端高温(42℃)":
            factor["t_out"] = 42.0
            self.out("【测试工况】室外极端高温 42℃，测试系统热负荷响应...", clear=False)
        elif ab_type == "变压器容量限载":
            self.engine.sys_config['safety']['transformer_capacity_kva'] = 1500.0
            self.out("【测试工况】变压器容量下调至 1500kVA，监测减载保护动作...", clear=False)
        elif ab_type == "低负荷防喘振测试":
            if isinstance(factor["r_zones"], dict):
                factor["r_zones"] = {z: (0.05 if self.engine.zone_can_use_chw(z) else 0.0) for z in self.engine.zones.keys()}
            else:
                factor["r_zones"] = [0.05] * len(self.engine.zones)
            factor["t_out"] = 26.0
            self.out("【测试工况】低负荷工况，验证防喘振保护和模式切换...", clear=False)
        elif ab_type == "多联机容量受限测试":
            self.engine.sys_config['equipment']['capacity_vrf_kw'] = 50.0
            self.out("【测试工况】VRF 容量限制为 50kW，验证容量越限保护...", clear=False)

        self.config_manager.scenarios["异常测试工况"] = factor
        if "异常测试工况" not in list(self.cb_scen['values']):
            self.cb_scen['values'] = list(self.cb_scen['values']) + ["异常测试工况"]
        self.cb_scen.set("异常测试工况")

        self.run_sim_async(run_type="abnormal_test")

        def restore_config():
            self.engine.sys_config['safety']['transformer_capacity_kva'] = old_kva
            self.engine.sys_config['equipment']['capacity_vrf_kw'] = old_vrf

        if ab_type in ["变压器容量限载", "多联机容量受限测试"]:
            self.root.after(3000, restore_config)

        parent_top.destroy()

    def show_calculation_basis(self):
        top = tk.Toplevel(self.root)
        top.title("参数与计算依据说明")
        top.geometry("700x560")
        txt = scrolledtext.ScrolledText(top, font=("微软雅黑", 10), padx=15, pady=15)
        txt.pack(fill=tk.BOTH, expand=True)
        basis = """【热力学计算依据】
- 负荷预测：采用 RC 热网等效物理模型计算围护结构热阻与室内热容。
- 动态 COP：冷水机组与 VRF 系统能效基于出水温度与负荷率的二维插值曲面动态计算。

【冷冻水流体力学依据】
- 冷量流量反算公式：Q = 1.163 × G × ΔT（水比热与密度折算常量）。
- 连续性方程流速：v = Q / (π·(D/2)²)。
- 管路阻力模型：速度平方型工程简化公式 (h = K·v²)。
- 阀门开度模型：基于各支路即时负荷占比的等百分比特性估算。

【生命周期经济性 (LCC) 依据】
- 节流收益精算：同步考虑峰平谷分时电价（TOU）。
- NPV 模型：15年运行周期下的财务净现值估算，贴现率 5%。
- 注意：本估算基于典型日+季节系数推算，非完整 8760 小时审计，仅供参考。

【云端大模型边界约定】
- 云端 AI 仅提供运行模式（LOW/MID/HIGH）建议权。
- 本地 DDC 在变压器过载、室温超驰、喘振风险时否决云端指令并降级自愈。

【历史运行数据与训练边界说明】
- 历史运行数据可用于后续训练负荷预测模型、策略推荐模型和异常识别模型。
- 当前版本为仿真运行数据采集，不宣称接入现场真实传感器，不宣称完成真实项目 AI 训练。
- 策略对比和异常测试数据标记为不同 run_type，便于与常规运行样本区分。"""
        txt.insert(tk.END, basis)
        txt.config(state="disabled")

    def edit_current_scenario(self):
        s_name = self.cb_scen.get()
        base = self.config_manager.scenarios.get(s_name, DEFAULT_SCENARIOS["03_下午高峰"])
        factor = base.copy()

        top = tk.Toplevel(self.root)
        top.title(f"参数调整 - {s_name}")
        top.geometry("450x580")

        tk.Label(top, text="室外气象温度 (℃):").grid(row=0, column=0, pady=5, sticky="e")
        sc_tout = tk.Scale(top, from_=0, to=50, resolution=0.5, orient=tk.HORIZONTAL, length=180)
        sc_tout.set(factor.get("t_out", 33.5))
        sc_tout.grid(row=0, column=1)

        tk.Label(top, text="建筑运转系数 (0-1):").grid(row=1, column=0, pady=5, sticky="e")
        sc_sch = tk.Scale(top, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, length=180)
        sc_sch.set(factor.get("c_sch", 1.0))
        sc_sch.grid(row=1, column=1)

        tk.Label(top, text="人员出勤系数 (0-1):").grid(row=2, column=0, pady=5, sticky="e")
        sc_occ = tk.Scale(top, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, length=180)
        sc_occ.set(factor.get("c_occ", 0.95))
        sc_occ.grid(row=2, column=1)

        var_night = tk.BooleanVar(value=factor.get("is_night", False))
        tk.Checkbutton(top, text="激活夜间保温模式", variable=var_night).grid(row=3, column=0, columnspan=2, pady=5)

        tk.Label(top, text="【各区域占用率】", font=("微软雅黑", 9, "bold"), fg="#8E44AD").grid(row=4, column=0, columnspan=2, pady=5)

        r_zones_input = factor.get("r_zones", {})
        zone_keys = list(self.engine.zones.keys())
        r_zones_dict = {}
        if isinstance(r_zones_input, list):
            for i, z in enumerate(zone_keys):
                r_zones_dict[z] = r_zones_input[i] if i < len(r_zones_input) else 0.75
        else:
            for z in zone_keys:
                r_zones_dict[z] = r_zones_input.get(z, 0.75)

        zone_vars = {}
        row_idx = 5
        for z in zone_keys:
            tk.Label(top, text=f"{z}:").grid(row=row_idx, column=0, pady=2, sticky="e")
            sc_z = tk.Scale(top, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, length=180)
            sc_z.set(r_zones_dict[z])
            sc_z.grid(row=row_idx, column=1)
            zone_vars[z] = sc_z
            row_idx += 1

        def apply_override():
            new_factor = {
                "t_out": sc_tout.get(),
                "c_sch": sc_sch.get(),
                "c_occ": sc_occ.get(),
                "is_night": var_night.get(),
                "r_zones": {z: var.get() for z, var in zone_vars.items()}
            }
            self.config_manager.scenarios["自定义参数工况"] = new_factor
            if "自定义参数工况" not in list(self.cb_scen['values']):
                self.cb_scen['values'] = list(self.cb_scen['values']) + ["自定义参数工况"]
            self.cb_scen.set("自定义参数工况")
            messagebox.showinfo("成功", "工况参数已更新！")
            top.destroy()

        tk.Button(top, text="保存并应用参数", bg="#E67E22", fg="white", font=("微软雅黑", 10, "bold"),
                  command=apply_override).grid(row=row_idx, column=0, columnspan=2, pady=15)

    def show_system_topology(self):
        if not self.last_res:
            messagebox.showwarning("无数据", "请先执行一次单步仿真。")
            return
        top = tk.Toplevel(self.root)
        top.title("系统物理拓扑映射")
        top.geometry("800x450")
        canvas = tk.Canvas(top, bg="#ECF0F1")
        canvas.pack(fill=tk.BOTH, expand=True)
        hyd = self.last_res.get("hydraulic", {})
        is_sleep = hyd.get("is_sleep", True)
        color = "#95A5A6" if is_sleep else "#2980B9"

        canvas.create_rectangle(50, 150, 150, 250, fill=color, outline="black")
        canvas.create_text(100, 200, text="冷水机组\n(源侧)", fill="white", font=("微软雅黑", 12, "bold"))
        canvas.create_rectangle(250, 175, 330, 225, fill="#27AE60" if not is_sleep else "#95A5A6", outline="black")
        canvas.create_text(290, 200, text="变频水泵", fill="white", font=("微软雅黑", 10, "bold"))
        canvas.create_rectangle(430, 100, 480, 300, fill="#7F8C8D", outline="black")
        canvas.create_text(455, 200, text="分\n集\n水\n器", fill="white", font=("微软雅黑", 12, "bold"))
        canvas.create_rectangle(650, 120, 750, 280, fill="#8E44AD" if not is_sleep else "#95A5A6", outline="black")
        canvas.create_text(700, 200, text="末端盘管\n(荷侧)", fill="white", font=("微软雅黑", 11, "bold"))

        canvas.create_line(150, 200, 250, 200, arrow=tk.LAST, width=3, fill=color)
        canvas.create_line(330, 200, 430, 200, arrow=tk.LAST, width=3, fill=color)
        canvas.create_line(480, 150, 650, 150, arrow=tk.LAST, width=2, fill=color)
        canvas.create_line(650, 250, 480, 250, arrow=tk.LAST, width=2, fill=color)
        canvas.create_line(455, 300, 455, 350, 100, 350, 100, 250, arrow=tk.LAST, width=3, fill=color)

        if is_sleep:
            canvas.create_text(400, 50, text="系统状态：中央水系统休眠", fill="red", font=("微软雅黑", 14, "bold"))
        else:
            canvas.create_text(400, 50,
                               text=f"总流量: {hyd.get('total_flow_m3h', 0)} m³/h | 泵功率: {hyd.get('pump_power_kw', 0)} kW",
                               fill="black", font=("微软雅黑", 12, "bold"))
            canvas.create_text(200, 180, text=f"{hyd.get('supply_temp_c', 7.0)} ℃", fill="blue")
            canvas.create_text(380, 180, text=f"{hyd.get('pump_head_kpa', 0.0)} kPa", fill="blue")
            canvas.create_text(550, 130, text="供水干管", fill="blue")
            canvas.create_text(550, 270, text=f"回水 {hyd.get('return_temp_c', 12.0)} ℃", fill="red")

    def generate_defense_summary(self):
        if not self.last_res:
            messagebox.showwarning("无数据", "请先执行一次单步仿真。")
            return
        res = self.last_res
        hyd = res.get("hydraulic", {})
        strat = self.strategy_var.get()
        branches = hyd.get("branches", [])
        active_branches = [b for b in branches if b.get("velocity_ms", 0) > 0]
        max_vel = max((b['velocity_ms'] for b in active_branches), default=0)

        summary = (
            "【运行结论说明】\n\n"
            "1. 控制架构：系统采用[云端建议 + 本地 DDC 白箱把控]双层架构。当前策略为 "
            + strat + "。\n"
            "2. 数字孪生：水力系统总流量 " + str(hyd.get('total_flow_m3h', 0))
            + " m3/h，水泵轴功率 " + str(hyd.get('pump_power_kw', 0))
            + " kW，最高流速 " + str(max_vel) + " m/s，符合工程规范。\n"
            "3. 效益精算：单步节能率 " + str(res.get('rate_disp', '0%'))
            + "。水力阻力参数为工程假定，具备实施阶段接入施工图或 BIM 数据的扩展能力。"
        )
        self.out("\n" + "=" * 60 + "\n" + summary + "\n" + "=" * 60 + "\n", clear=False)

    def open_api_settings(self):
        top = tk.Toplevel(self.root)
        top.title("API 供应商参数设置")
        top.geometry("450x340")

        tk.Label(top, text="选择供应商:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        cb_prov = ttk.Combobox(top, values=list(PROV_NAME_TO_KEY.keys()), state="readonly")
        cb_prov.grid(row=0, column=1, pady=10)

        tk.Label(top, text="Base URL:").grid(row=1, column=0, padx=10, pady=5, sticky="e")
        e_url = tk.Entry(top, width=35)
        e_url.grid(row=1, column=1, pady=5)

        tk.Label(top, text="模型名称(Model):").grid(row=2, column=0, padx=10, pady=5, sticky="e")
        e_model = tk.Entry(top, width=35)
        e_model.grid(row=2, column=1, pady=5)

        tk.Label(top, text="API Key:").grid(row=3, column=0, padx=10, pady=5, sticky="e")
        e_key = tk.Entry(top, width=35, show="*")
        e_key.grid(row=3, column=1, pady=5)

        def on_prov_change(event=None):
            prov_name = cb_prov.get()
            if not prov_name:
                return
            prov_key = PROV_NAME_TO_KEY.get(prov_name, "")
            cfg = self.config_manager.get_provider_config(prov_key)
            e_url.delete(0, tk.END)
            e_model.delete(0, tk.END)
            e_key.delete(0, tk.END)
            e_url.insert(0, cfg.get("base_url", ""))
            e_model.insert(0, cfg.get("model", ""))
            e_key.insert(0, cfg.get("api_key", ""))

        cb_prov.bind("<<ComboboxSelected>>", on_prov_change)
        cb_prov.set("千问 / 阿里云百炼")
        on_prov_change()

        def reset_default():
            prov_key = PROV_NAME_TO_KEY.get(cb_prov.get(), "")
            preset = PROVIDER_PRESETS.get(prov_key, {})
            e_url.delete(0, tk.END)
            e_model.delete(0, tk.END)
            e_url.insert(0, preset.get("base_url", ""))
            e_model.insert(0, preset.get("model", ""))

        def save():
            prov_key = PROV_NAME_TO_KEY.get(cb_prov.get(), "")
            self.config_manager.api_config["active_provider"] = prov_key
            self.config_manager.save_api_config(prov_key, e_url.get(), e_model.get(), e_key.get())
            messagebox.showinfo("成功", f"【{cb_prov.get()}】参数已保存。", parent=top)
            top.destroy()

        tk.Button(top, text="恢复默认", bg="#E67E22", fg="white", command=reset_default).grid(row=4, column=0, pady=15, padx=5)
        tk.Button(top, text="保存设置", bg="#27AE60", fg="white", command=save).grid(row=4, column=1, pady=15, padx=5)
        tk.Label(top, text="API Key 仅保存在本地 config_api.json 中，不写入源码。", fg="grey").grid(row=5, column=0, columnspan=2, pady=2)

    def test_api(self):
        cfg_entry = STRATEGY_REGISTRY.get(self.strategy_var.get())
        if cfg_entry["type"] == "local":
            messagebox.showinfo("提示", "本地控制算法，无需测试云端连接。")
            return
        client = LLMClient(cfg_entry["provider"], self.config_manager.api_config)
        if not client.is_configured():
            messagebox.showerror("错误", "API 配置不完整：请在 API 设置中填写 Base URL、模型名称和 API Key。")
            return
        self.out("API 连接测试中，请稍候...", clear=True)
        self.set_buttons_state("disabled")

        def worker():
            ok, msg = client.test_connection()
            def update_ui():
                self.set_buttons_state("normal")
                if ok:
                    messagebox.showinfo("测试成功", msg)
                    self.out(f"连接正常: {msg}")
                else:
                    messagebox.showerror("连接失败", msg)
                    self.out(f"连接失败: {msg}")
            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()


    def export_point_ledger_template(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="通用建筑机电测点台账模板.json"
        )
        if not p:
            return
        success, msg = self.config_manager.export_point_ledger_template(p)
        if success:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导出失败", msg)

    def export_point_ledger_csv_templates(self):
        folder = filedialog.askdirectory(title="选择CSV台账模板导出文件夹")
        if not folder:
            return
        success, msg = self.config_manager.export_point_ledger_csv_templates(folder)
        if success:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导出失败", msg)

    def import_point_ledger(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        success, msg = self.config_manager.load_external_point_ledger(p)
        if success:
            messagebox.showinfo("成功", msg + "\n已可在【测点联动分析】中选择房间/支路级对象。")
            self.out("已导入机电测点台账：房间、冷冻水管路、风管、冷却水系统和BAS/DDC点位已进入测点联动分析模块。", clear=False)
        else:
            messagebox.showerror("导入失败", msg)

    def import_scenarios(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        success, msg = self.config_manager.load_external_scenarios(p)
        if success:
            self.cb_scen.config(values=list(self.config_manager.scenarios.keys()))
            self.cb_scen.set(list(self.config_manager.scenarios.keys())[0])
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def import_building_config(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        success, msg, loaded_keys = self.config_manager.load_external_config(p)
        if success:
            bldgs = list(self.config_manager.building_configs.keys())
            self.cb_bldg.config(values=bldgs)
            new_bldg = loaded_keys[-1] if loaded_keys else bldgs[-1]
            self.cb_bldg.set(new_bldg)
            self.engine.load_building(new_bldg)
            self.reset_platform()
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def import_sequence_plan_ui(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        success, msg = self.config_manager.load_external_sequence(p)
        if success:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def export_current_report(self):
        text_content = self.txt_out.get(1.0, tk.END).strip()
        if not text_content:
            messagebox.showwarning("提示", "报告内容为空，请先执行仿真。")
            return
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("TXT", "*.txt")], initialfile="系统运行仿真报告.txt")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(text_content)
            messagebox.showinfo("成功", "报告已导出。")
        except Exception as e:
            log_error("MainPlatformGUI.export_current_report", e)
            messagebox.showerror("导出失败", str(e))

    def export_training_data(self):
        if not os.path.exists(self.history_logger.file_path):
            messagebox.showwarning("无数据", "暂无历史运行数据，请先执行仿真。")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="training_dataset.csv")
        if not p:
            return
        try:
            shutil.copy(self.history_logger.file_path, p)
            messagebox.showinfo("成功", f"历史运行数据集已导出至:\n{p}")
        except Exception as e:
            log_error("MainPlatformGUI.export_current_report", e)
            messagebox.showerror("导出失败", str(e))

    def show_welcome_info(self):
        msg = (
            "《配置驱动型·智慧建筑空调群控数字孪生平台》\n\n"
            "本系统基于软硬件解耦与参数外置驱动设计，默认加载通用公共建筑模板，竞赛案例可切换至校园综合体示例或通过JSON导入。\n\n"
            "▶ 参数驱动：建筑、房间、冷冻水管、风管、冷却水管和BAS/DDC点位均可通过台账模板导入。\n"
            "▶ 策略多样：支持本地规则控制、本地MPC预测控制和云端AI调度协同。\n"
            "▶ 安全闭环：云端AI仅提供运行模式建议，本地DDC白箱层负责最终执行审核。\n\n"
            "【提示】默认已选择[03_下午高峰]工况，点击[单步仿真]可查看水力流程数据；点击[测点联动分析]可查看房间/支路/点位级联动。\n"
            "首次单步运行受模态防抖和热惯性缓冲影响，建议配合[全天时序仿真]查看长效趋势。"
        )
        self.out(msg, clear=True)

    def run_sim_async(self, run_type="single_step"):
        self.set_buttons_state("disabled")
        s_name = self.cb_scen.get()
        factor = self.config_manager.scenarios.get(s_name, DEFAULT_SCENARIOS["03_下午高峰"]).copy()
        strategy = self._get_current_strategy(is_sequence=False)
        ui_name = self.strategy_var.get()
        cfg_entry = STRATEGY_REGISTRY.get(ui_name, {})

        # 检查工况r_zones缺省区域
        if isinstance(factor.get("r_zones"), dict):
            missing = [z for z in self.engine.zones if z not in factor["r_zones"]]
            if missing:
                self.out(f"【提示】工况 '{s_name}' 缺少区域 {missing} 的负荷率，已自动填充 0.75。\n", clear=False)

        self.out("仿真计算中，请稍候...", clear=False)

        def worker():
            try:
                req_mode = strategy.decide_mode(self.engine, factor, dt=15)
                ai_info = strategy.get_last_info()
            except Exception as e:
                req_mode = "LOW"
                ai_info = {
                    "recommended_mode": "LOW",
                    "reason": "策略调用失败，已切回默认模式",
                    "risk_note": str(e)[:50],
                    "confidence": 1.0,
                    "fallback": True
                }

            def update_ui():
                try:
                    res = self.engine.execute_step(factor, strategy=strategy, forced_mode=req_mode,
                                                   ai_info=ai_info, dt=15, accumulate_lcc=False)
                    self.last_res = res

                    self.history_logger.log_step(self.cb_bldg.get(), s_name, res,
                                                 factor=factor, engine=self.engine, run_type=run_type)

                    self.ai_mode_var.set(res.get("ai_requested_mode", "-"))
                    self.ai_source_var.set(ui_name)
                    self.ai_risk_var.set(ai_info.get("risk_note", "-"))
                    self.ai_conf_var.set(f"{ai_info.get('confidence', 0) * 100:.1f}%")

                    if ai_info.get("fallback", False):
                        self.ai_fallback_var.set("是 (已切回本地控制)")
                        self.ai_reason_var.set("API调用失败，已切回本地MPC")
                    else:
                        self.ai_fallback_var.set("否" if cfg_entry.get("type") == "cloud" else "不适用(本地控制)")
                        self.ai_reason_var.set(ai_info.get("reason", "-"))

                    # BiLSTM 云端引擎状态面板刷新（含未启用态降级展示）
                    self._update_bilstm_panel(ai_info, res)
                    # 云端 BiLSTM 断网降级时同步推送告警条到控制台，提升操作员感知
                    if (cfg_entry.get("provider") == "bilstm"
                            and ai_info.get("fallback") is True):
                        self.out("WARN | 云端 BiLSTM 断开，无缝降级至本地 MPC 策略", clear=False)

                    for item in self.tv_hyd.get_children():
                        self.tv_hyd.delete(item)
                    hyd_res = res.get("hydraulic", {})
                    if hyd_res.get("is_sleep", True):
                        self.tv_hyd.insert("", "end", values=(
                            "全网管道", "休眠待命", "0.0", "0.0", "0.0", "0.0", "0.0", "--", "--", "系统休眠"
                        ), tags=('sleep',))
                    else:
                        for b in hyd_res.get("branches", []):
                            tag = ('alert',) if b["warning"] else ()
                            self.tv_hyd.insert("", "end", values=(
                                b["zone_name"], b["terminal_type"], b["cooling_kw"],
                                b["air_flow_m3h"], b["flow_m3h"], b["valve_opening"],
                                b["branch_total_dp_kpa"], b["supply_air_temp"], b["return_air_temp"],
                                "仿真公式计算"
                            ), tags=tag)

                    self.out(self.agent.generate_report(res, s_name, is_single_step=True))
                    self.out(f"\n▶ 本步数据已写入历史运行记录：{self.history_logger.file_path}", clear=False)
                except Exception as e:
                    log_error("MainPlatformGUI.run_sim_async.update_ui", e)
                    self.out(f"仿真执行异常: {e}", clear=False)
                finally:
                    self.set_buttons_state("normal")

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def run_sequence_async(self):
        self.set_buttons_state("disabled")
        self.out("正在执行全天时序仿真，请稍候...", clear=True)
        strategy = self._get_current_strategy(is_sequence=True)
        building_name = self.cb_bldg.get()

        def worker():
            try:
                sim_data = self.sim_runner.execute_sequence(
                    self.config_manager.scenarios,
                    self.config_manager.sequence_plan,
                    strategy,
                    logger=self.history_logger,
                    building_name=building_name,
                    run_type="sequence"
                )
            except Exception as e:
                sim_data = None
                def show_error():
                    messagebox.showerror("仿真失败", str(e))
                    self.out(f"仿真执行异常: {e}")
                self.root.after(0, show_error)
                return

            def update_ui():
                self.set_buttons_state("normal")
                if sim_data:
                    # 序列仿真终态：刷新 BiLSTM 状态面板并按需推送降级告警，与单步路径对齐
                    last_ai_info = strategy.get_last_info() if hasattr(strategy, 'get_last_info') else {}
                    last_res = sim_data.get("h_data", [])[-1] if sim_data.get("h_data") else {}
                    self._update_bilstm_panel(last_ai_info, last_res)
                    cfg_entry_seq = STRATEGY_REGISTRY.get(self.strategy_var.get(), {})
                    if (cfg_entry_seq.get("provider") == "bilstm"
                            and last_ai_info.get("fallback") is True):
                        self.out("WARN | 云端 BiLSTM 断开，无缝降级至本地 MPC 策略", clear=False)
                    self._show_sequence_window(sim_data)

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def run_comparison_async(self):
        self.set_buttons_state("disabled")
        self.out("策略对比仿真启动中（对比数据不写入训练历史），请稍候...", clear=True)
        building_name = self.cb_bldg.get()

        def worker():
            try:
                sim_rule = self.sim_runner.execute_sequence(
                    self.config_manager.scenarios, self.config_manager.sequence_plan,
                    RuleBasedStrategy(), logger=None, building_name=building_name, run_type="comparison"
                )
                sim_mpc = self.sim_runner.execute_sequence(
                    self.config_manager.scenarios, self.config_manager.sequence_plan,
                    MPCStrategy(), logger=None, building_name=building_name, run_type="comparison"
                )
            except Exception as e:
                def show_error():
                    messagebox.showerror("对比仿真失败", str(e))
                    self.set_buttons_state("normal")
                self.root.after(0, show_error)
                return

            def update_ui():
                self.set_buttons_state("normal")
                self.out("策略对比仿真完成。")
                if sim_rule and sim_mpc:
                    self._show_comparison_window(sim_rule, sim_mpc)

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _show_sequence_window(self, sim_data):
        if not sim_data:
            return
        top = tk.Toplevel(self.root)
        top.title("全天时序仿真监控中心")
        top.geometry("1180x780")

        fig = Figure(figsize=(9, 4), dpi=100)
        fig.subplots_adjust(bottom=0.25, top=0.88)
        ax1 = fig.add_subplot(111)
        ax1.set_title('典型日功率负荷与室温推演曲线', fontdict={'weight': 'bold', 'size': 12})

        l1, = ax1.plot(sim_data["times"], sim_data["trad_ps"], color='#7F8C8D', linestyle='--', label='传统基准功率(kW)', alpha=0.6)
        l2, = ax1.plot(sim_data["times"], sim_data["opt_ps"], color='#27AE60', linestyle='-', label='优化调度功率(kW)', linewidth=2)
        ax2 = ax1.twinx()
        l3, = ax2.plot(sim_data["times"], sim_data["t_ins"], color='#C0392B', linestyle='-', label='室内温度(℃)', linewidth=1.5)
        l4, = ax2.plot(sim_data["times"], sim_data["t_outs"], color='#E67E22', linestyle=":", label='室外温度(℃)', linewidth=1.5)
        l5 = ax2.axhline(y=self.engine.sys_config['safety']['indoor_temp_limit'], color='#C0392B', linestyle='--', alpha=0.5, label='室温安全上限')

        ax1.set_xlabel('时间(h)', fontdict={'weight': 'bold'})
        ax1.set_ylabel('功率(kW)', fontdict={'weight': 'bold'})
        ax2.set_ylabel('温度(℃)', color='#C0392B')

        lines = [l1, l2, l3, l4, l5]
        labels = [l.get_label() for l in lines]
        for idx, sp in enumerate(sim_data["switches"]):
            lv = ax1.axvline(x=sp, color='k', linestyle=':', alpha=0.4)
            if idx == 0:
                lv.set_label('模态切换点')
                lines.append(lv)
                labels.append('模态切换点')

        ax1.legend(lines, labels, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, frameon=True, fontsize=9)

        canvas = FigureCanvasTkAgg(fig, master=top)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=False, pady=5)

        cols = ("时间", "模式", "需求冷量(kW)", "交付冷量(kW)", "冷冻水流量(m³/h)",
                "水泵功率(kW)", "供冷状态", "优化功率(kW)", "室温(℃)", "节能率")
        tv = ttk.Treeview(top, columns=cols, show='headings', height=8)
        tv.tag_configure('alert', foreground='red')
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=110 if c in ("冷冻水流量(m³/h)", "供冷状态", "模式") else 85, anchor="center")
        tv.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        for d in sim_data["h_data"]:
            has_alarm = len(d['cmd'].get('alarms', [])) > 0 or d['cooling_satisfaction_val'] < 0.95
            is_standby = "待机" in d.get('cooling_satisfaction_disp', '')
            tag = ('alert',) if has_alarm and not is_standby else ()
            hyd_node = d.get('hydraulic', {})
            tv.insert("", "end", values=(
                f"{d['time']/60:.2f} h",
                MODE_LABELS.get(d['combo'], d['combo']),
                d['load'], d['delivered'],
                hyd_node.get('total_flow_m3h', 0.0),
                hyd_node.get('pump_power_kw', 0.0),
                d['cooling_satisfaction_disp'],
                d['opt_p'], d['t_in'], d['rate_disp']
            ), tags=tag)

        fr_b = tk.Frame(top)
        fr_b.pack(fill=tk.X, pady=10)

        def export_csv():
            file_path = filedialog.asksaveasfilename(
                parent=top, defaultextension=".csv",
                filetypes=[("CSV", "*.csv")], initialfile="全时序审计矩阵.csv"
            )
            if not file_path:
                return
            try:
                with open(file_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(cols)
                    for item in tv.get_children():
                        writer.writerow(tv.item(item)["values"])
                messagebox.showinfo("导出成功", "审计矩阵已保存！", parent=top)
            except Exception as ex:
                messagebox.showerror("导出失败", str(ex), parent=top)

        tk.Button(fr_b, text="导出 CSV", bg="#117A65", fg="white", font=("微软雅黑", 9), command=export_csv).pack(side=tk.RIGHT, padx=20)

        lcc = sim_data.get("lcc_info")
        if lcc:
            lcc_text = (
                f"【LCC 经济性估算】 策略: {sim_data['strat_type']} | "
                f"累计节电: {sim_data['total_kwh_saved']:.2f} kWh | "
                f"年化节费: {lcc['Annual_Saving']} 万元 | 15年NPV: {lcc['NPV']} 万元"
            )
            tk.Label(fr_b, text=lcc_text, font=("微软雅黑", 10, "bold"), fg="#117A65", justify=tk.LEFT).pack(side=tk.LEFT, padx=20)

    def _show_comparison_window(self, sim_rule, sim_mpc):
        if not sim_rule or not sim_mpc:
            return
        top = tk.Toplevel(self.root)
        top.title("规则控制 vs MPC 预测控制 对比")
        top.geometry("1100x600")

        fig = Figure(figsize=(9, 4), dpi=100)
        fig.subplots_adjust(bottom=0.25, top=0.88)
        ax1 = fig.add_subplot(111)
        ax1.set_title('规则控制 vs 预测寻优', fontdict={'weight': 'bold', 'size': 12})

        l1, = ax1.plot(sim_rule["times"], sim_rule["trad_ps"], color='#95A5A6', linestyle='--', label='传统基准功率(kW)')
        l2, = ax1.plot(sim_rule["times"], sim_rule["opt_ps"], color='#F39C12', linestyle='-', label='规则控制功率(kW)')
        l3, = ax1.plot(sim_mpc["times"], sim_mpc["opt_ps"], color='#27AE60', linestyle='-', label='预测寻优功率(kW)')
        ax2 = ax1.twinx()
        l4, = ax2.plot(sim_rule["times"], sim_rule["t_ins"], color='#E74C3C', linestyle=':', label='规则室内温度(℃)', alpha=0.7)
        l5, = ax2.plot(sim_mpc["times"], sim_mpc["t_ins"], color='#C0392B', linestyle='-', label='寻优室内温度(℃)')
        l6 = ax2.axhline(y=self.engine.sys_config['safety']['indoor_temp_limit'], color='r', linestyle='-.', alpha=0.4, label='室温安全上限')

        ax1.set_xlabel('时间(h)', fontdict={'weight': 'bold'})
        ax1.set_ylabel('功率(kW)', fontdict={'weight': 'bold'})
        ax2.set_ylabel('温度(℃)', color='#C0392B')
        all_lines = [l1, l2, l3, l4, l5, l6]
        ax1.legend(all_lines, [l.get_label() for l in all_lines],
                   loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, frameon=True, fontsize=9)

        canvas = FigureCanvasTkAgg(fig, master=top)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=False, pady=5)

        fr_b = tk.Frame(top)
        fr_b.pack(fill=tk.X, pady=10, padx=20)

        def fmt(s):
            lcc = s.get("lcc_info")
            return (
                f"节电: {s['total_kwh_saved']:.1f} kWh | "
                f"年化节费: {lcc['Annual_Saving'] if lcc else 0} 万 | "
                f"NPV: {lcc['NPV'] if lcc else 0} 万 | "
                f"供冷不足: {s['cooling_deficit_count']} 次 | "
                f"安全超驰: {s['safety_override_count']} 次"
            )

        tk.Label(fr_b, text=f"【规则控制】 {fmt(sim_rule)}", font=("微软雅黑", 10), fg="#F39C12", anchor="w").pack(fill=tk.X, pady=2)
        tk.Label(fr_b, text=f"【预测寻优】 {fmt(sim_mpc)}", font=("微软雅黑", 10, "bold"), fg="#27AE60", anchor="w").pack(fill=tk.X, pady=2)

    def trigger_estop(self):
        if not self.engine.e_stop_active:
            self.engine.execute_step({}, forced_mode=None, dt=0, is_estop=True)
            self.out("急停：主断路器强断，DDC 控制输出锁死。", clear=True)
            self.btn_estop.config(text="解除急停强复位", bg="#E67E22", command=self.release_estop)

    def release_estop(self):
        self.engine.release_estop_state()
        self.btn_estop.config(text="强断急停", bg="#CB4335", command=self.trigger_estop)
        self.out("解除成功：电网重送，底层自控功能恢复。", clear=True)

    def reset_platform(self):
        self.engine.reset_state(full=True)
        self.last_res = None
        self.ai_mode_var.set("-")
        self.ai_reason_var.set("-")
        self.ai_risk_var.set("-")
        self.ai_conf_var.set("-")
        self.ai_source_var.set("-")
        self.ai_fallback_var.set("-")
        # BiLSTM 云端状态面板复位至待启动态
        try:
            self.bilstm_status_label.config(text="● 待启动", fg="#64748B")
        except Exception:
            pass
        if hasattr(self, "bilstm_load_var"):
            self.bilstm_load_var.set("预测 t+1: --\n实际仿真: --")
        if hasattr(self, "bilstm_conf_var"):
            self.bilstm_conf_var.set("--")
        if hasattr(self, "bilstm_latency_var"):
            self.bilstm_latency_var.set("--")
        # 重置边缘侧性能监控条
        for _attr, _default in [
            ("edge_latency_ai_var",  "-- ms"),
            ("edge_latency_opt_var", "-- ms"),
            ("edge_mem_var",         "-- MB"),
        ]:
            if hasattr(self, _attr):
                getattr(self, _attr).set(_default)
        for item in self.tv_hyd.get_children():
            self.tv_hyd.delete(item)
        # 重置急停按钮状态
        self.btn_estop.config(text="强断急停", bg="#CB4335", command=self.trigger_estop)
        self.out("仿真状态已重置：热惯性、状态机、LCC账本、水力数据、事件日志均已清零。", clear=True)

    def show_logs(self):
        top = tk.Toplevel(self.root)
        top.title("DDC 安全监控审计日志")
        top.geometry("700x450")
        txt = scrolledtext.ScrolledText(top, font=("Consolas", 10))
        txt.pack(fill=tk.BOTH, expand=True)
        logs = self.engine.event_log if hasattr(self.engine, "event_log") and self.engine.event_log else []
        txt.insert(tk.END, "\n".join(logs) if logs else "暂无事件日志。")


# =====================================================================
# 程序入口
# =====================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = MainPlatformGUI(root)
    root.mainloop()
