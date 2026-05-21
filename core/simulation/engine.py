"""White-box closed-loop simulation engine.

Port of the legacy ``WhiteBoxEngine`` class (banner-adjusted lines
2077-2790 of the frozen reference module under ``legacy/``) with three
architectural changes:

1. **No LLM-in-control.** The legacy inline strategy invocation block
   (legacy 2280-2305) and the inline indoor-temperature safety override
   block (legacy 2272-2278) are deleted. They are replaced by a single
   call to :meth:`core.control.control_chain.ControlChain.step`, which
   runs the five layers (Prediction -> Optimization -> Rule -> Safety
   -> Execution) and returns a :class:`ControlCommand`. The dict-shaped
   ``cmd`` consumed by the rest of ``execute_step`` is then synthesised
   from that command.
2. **Strategy / supervisor / predictor injection.** The constructor now
   accepts the strategy, safety supervisor, predictor and control chain
   as optional dependencies. Defaults reproduce the legacy behaviour
   (rule-based strategy, supervisor sourced from ``sys_config``, no
   predictor, fresh control chain).
3. **No UI back-pointer.** ``self.ui_reference`` has been removed.
   Per-step physics frames are dispatched through ``self.frame_callbacks``,
   a list of ``Callable[[dict], None]`` callables registered by the
   service / UI layer.

All other simulation logic -- mode-switch anti-chatter, hydraulic
recompute, LCC accumulation, transformer protection, alarm formatting --
is preserved verbatim.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from core.control.control_chain import ControlChain
from core.control.strategies import BaseStrategy, RuleBasedStrategy
from core.economics import LCCEstimator
from core.optimizer.chiller_group import ChillerGroupOptimizer
from core.physics.hydraulic import HydraulicNetworkModel
from core.physics.simulation_engine import PhysicsSimulationEngine
from core.physics.thermal import RoomRCModel, ThermalBuffer
from core.safety.supervisor import ControlCommand, SafetySupervisor
from models.equipment import EquipmentModel, EquipmentRegistry
from utils.logging import get_logger

_logger = get_logger(__name__)


class WhiteBoxEngine:
    """Closed-loop white-box simulation engine."""

    def __init__(
        self,
        config_manager: Any,
        building_key: str,
        strategy: BaseStrategy | None = None,
        supervisor: SafetySupervisor | None = None,
        predictor: Any | None = None,
        control_chain: ControlChain | None = None,
    ) -> None:
        self.config_mgr = config_manager
        self.sys_config = config_manager.sys_config
        self.lcc = LCCEstimator(self.sys_config)
        self.thermal = ThermalBuffer()
        self.rc_model = RoomRCModel(self.sys_config)
        self.registry = EquipmentRegistry()
        self._build_registry()
        # Group-control SLSQP allocator.
        self.chiller_optimizer = ChillerGroupOptimizer(
            central_model=self.registry.get('central'),
            sys_config=self.sys_config,
        )
        self.load_building(building_key)
        self._is_silent = False
        self.reset_state(full=True)

        # Five-layer control chain dependencies.
        self.strategy: BaseStrategy = strategy if strategy is not None else RuleBasedStrategy()
        self.supervisor: SafetySupervisor = (
            supervisor if supervisor is not None else SafetySupervisor(self.sys_config)
        )
        self.predictor = predictor
        self.control_chain: ControlChain = (
            control_chain if control_chain is not None else ControlChain()
        )

        # In-process physics simulator used to populate the per-step
        # process-level frame dispatched to ``self.frame_callbacks``.
        self.physics_engine = PhysicsSimulationEngine()

        # UI/service back-pointer replacement: a list of frame callbacks.
        # Anything that wants per-step physics state registers a callable
        # via ``self.frame_callbacks.append(my_cb)``; the engine never
        # imports Tk / queue.
        self.frame_callbacks: list[Callable[[dict], None]] = []

    # ----------------------------------------------------------- registry
    def _build_registry(self) -> None:
        t_out_arr = np.array(self.sys_config['cop_tables']['T_out'])
        plr_arr = np.array(self.sys_config['cop_tables']['PLR'])
        for stype in ['central', 'vrf', 'base']:
            data = np.array(self.sys_config['cop_tables'][stype])
            interp = RegularGridInterpolator(
                (t_out_arr, plr_arr), data, bounds_error=False, fill_value=np.nan,
            )
            self.registry.register(stype, EquipmentModel(stype, interp))

    def load_building(self, building_key: str) -> None:
        keys = list(self.config_mgr.building_configs.keys())
        bk = building_key if building_key in keys else keys[0]
        self.b_cfg = self.config_mgr.building_configs[bk]
        self.zone_specs: dict[str, dict] = {}
        self.zones: dict[str, float] = {}
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
                    "design_airflow_m3h": float(zv.get(
                        "design_airflow_m3h",
                        float(zv.get("design_load_kw", 1000.0)) * 250.0,
                    )),
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
                    "design_airflow_m3h": float(zv) * 250.0,
                }
        self.th = self.b_cfg.get("th", {"high": 6000.0, "mid": 2200.0})
        self.tau = self.b_cfg.get("tau", 25)
        self.hydraulic_model = HydraulicNetworkModel(self.zone_specs, self.sys_config)

    def zone_can_use_chw(self, zone: str) -> bool:
        return self.zone_specs.get(zone, {}).get("system_type", "CHW") in ["CHW", "BOTH"]

    def zone_can_use_vrf(self, zone: str) -> bool:
        return self.zone_specs.get(zone, {}).get("system_type", "VRF") in ["VRF", "BOTH"]

    def zone_is_none(self, zone: str) -> bool:
        return self.zone_specs.get(zone, {}).get("system_type", "CHW") == "NONE"

    # ---------------------------------------------------------- state mgmt
    def reset_state(self, full: bool = True) -> None:
        if full:
            self.sim_time = 0
            self.current_mode = "LOW"
            self.time_in_mode = 0
            self.current_chillers = 0
            self.time_in_staging = 0
            self.vrf_start_history: list = []
            self.event_log: list[str] = []
            self.thermal.step(0, 0, self.tau, reset=True)
            self.rc_model.t_in = 24.0
            self.lcc.total_kwh_saved = 0.0
            self.lcc.total_cost_saved = 0.0
        self.switch_count = 0
        self.e_stop_active = False

    def export_state(self) -> dict:
        return {
            "sim_time": self.sim_time, "current_mode": self.current_mode,
            "time_in_mode": self.time_in_mode, "current_chillers": self.current_chillers,
            "time_in_staging": self.time_in_staging, "vrf_start_history": self.vrf_start_history.copy(),
            "thermal_prev_load": self.thermal.prev_load, "rc_t_in": self.rc_model.t_in,
            "switch_count": self.switch_count, "e_stop_active": self.e_stop_active,
            "lcc_kwh": self.lcc.total_kwh_saved, "lcc_cost": self.lcc.total_cost_saved,
            "is_silent": self._is_silent, "event_log": self.event_log.copy(),
        }

    def restore_state(self, st: dict) -> None:
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

    def release_estop_state(self) -> None:
        self.e_stop_active = False
        self.log_event("解除急停", "DDC 安全复位，控制输出恢复")

    def log_event(self, event_type: str, desc: str) -> None:
        if not getattr(self, "_is_silent", False):
            self.event_log.append(f"[T={self.sim_time}m] [{event_type}] {desc}")

    # ------------------------------------------------------------- inputs
    def _parse_inputs(self, factor: dict) -> tuple[float, dict, float, bool]:
        t_out = factor.get("t_out", 33.5)
        f_weather = max(0.3, 1.0 + 0.04 * (t_out - 33.5) if t_out > 26.0 else 0.45)
        zone_names = list(self.zones.keys())
        r_zones_input = factor.get("r_zones", {})
        zone_loads: dict[str, float] = {}
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
            zone_loads[z] = (
                self.zones[z] * rz
                * factor.get("c_sch", 1) * factor.get("c_occ", 1) * f_weather
            )
        target_load = sum(zone_loads.values())
        return t_out, zone_loads, target_load, factor.get("is_night", False)

    # ------------------------------------------------------------- step
    def execute_step(
        self,
        factor: dict,
        strategy: BaseStrategy | None = None,
        forced_mode: str | None = None,
        ai_info: dict | None = None,
        dt: float = 15,
        accumulate_lcc: bool = True,
        silent: bool = False,
        is_estop: bool = False,
    ) -> dict:
        # === Pre-state save ===
        prev_silent = self._is_silent
        self._is_silent = silent
        mode_before = self.current_mode

        # Resolve which strategy this call uses (per-call override allowed,
        # falling back to the engine-level injected strategy).
        active_strategy: BaseStrategy = strategy if strategy is not None else self.strategy

        # === E-stop processing ===
        if is_estop or self.e_stop_active:
            if is_estop and not self.e_stop_active:
                self.log_event("急停锁止", "硬件强断生效，控制输出挂起")
                self.e_stop_active = True
            self._is_silent = prev_silent
            frozen = self._frozen_state(ai_info)
            frozen["mode_before"] = mode_before
            return frozen

        # === 1. Load parsing + thermal buffer ===
        t_out, zone_loads, target_load, is_night = self._parse_inputs(factor)
        q_required = self.thermal.step(target_load, dt, self.tau)
        scale = q_required / target_load if target_load > 0 else 0.0
        zone_loads_dyn = {z: load * scale for z, load in zone_loads.items()}

        cmd: dict[str, Any] = {
            "alarms": [], "shedding_seq": [],
            "BACnet_AV_9001_LockTimer": "",
            "BACnet_DO_3001_Chiller_Units": 0,
            "BACnet_AO_4001_VRF_Demand_kW": 0.0,
            "BACnet_BI_3002_Chiller_RunStatus": 0,
            "BACnet_BI_4002_VRF_RunStatus": 0,
        }
        for i, z in enumerate(self.zones):
            cmd[f"BACnet_BO_500{i+1}_Valve_{z[:2]}"] = 0
            cmd[f"BACnet_BI_510{i+1}_Valve_{z[:2]}_FB"] = 0

        # === 2. Five-layer control chain ===
        # Build the engine_state dict the chain expects. Including
        # ``_engine``/``_factor``/``_dt`` lets the rule layer call the
        # injected strategy with full engine context (zones, zone_specs,
        # thresholds). ``forced_mode`` short-circuits the chain entirely
        # so the silent MPC look-ahead path stays as cheap as before.
        engine_state: dict[str, Any] = {
            "_engine": self,
            "_factor": factor,
            "_dt": dt,
            "current_mode": self.current_mode,
            "time_in_mode": float(self.time_in_mode),
            "t_in": self.rc_model.t_in,
            "t_out": t_out,
            "target_load_kw": float(q_required),
            "load_prev": float(self.thermal.prev_load or q_required),
            "th_high": float(self.th.get("high", 6000.0)),
            "th_mid": float(self.th.get("mid", 2200.0)),
            "is_night": bool(is_night),
            "c_sch": float(factor.get("c_sch", 1.0)),
            "c_occ": float(factor.get("c_occ", 1.0)),
            "hour": float(factor.get("hour", (self.sim_time / 60.0) % 24.0)),
            "comm_timeout": bool(factor.get("comm_timeout", False)),
            "ai_failure": bool(factor.get("ai_failure", False)),
            "fallback_mode": str(factor.get("fallback_mode", "LOW")),
        }

        # ── strategy dispatch via the control chain ────────────────────
        ai_info_resolved: dict | None = ai_info
        if forced_mode is not None:
            req_mode = forced_mode
            cmd_obj = ControlCommand(mode=req_mode, n_chillers=0)
        else:
            try:
                cmd_obj = self.control_chain.step(
                    engine_state=engine_state,
                    sys_config=self.sys_config,
                    strategy=active_strategy,
                    supervisor=self.supervisor,
                    predictor=self.predictor,
                )
                req_mode = cmd_obj.mode
            except Exception:
                _logger.exception("WhiteBoxEngine: control chain failed; defaulting to LOW")
                cmd_obj = ControlCommand(mode="LOW", n_chillers=0)
                req_mode = "LOW"

        if not req_mode:
            req_mode = "LOW"

        # Carry chain alarms forward into the dict-shaped cmd consumed by
        # the rest of execute_step.
        if cmd_obj.alarms:
            cmd["alarms"].extend(cmd_obj.alarms)

        safety_override_flag = bool(cmd_obj.overridden)
        # Indoor temp limit fires the "safety_override" branch in the
        # legacy hydraulic+staging anti-chatter logic. We treat any
        # supervisor override that altered the mode toward MID/HIGH the
        # same way (so the staging lock can be bypassed when needed).
        safety_override = safety_override_flag and cmd_obj.mode in ("MID", "HIGH")
        if safety_override:
            self.log_event(
                "安全超驰",
                f"控制链安全层触发 (mode={cmd_obj.mode}, 室温={self.rc_model.t_in:.1f}℃)",
            )

        des_mode = cmd_obj.mode if forced_mode is None else forced_mode

        # === 3. Mode-switch anti-chatter ===
        is_switching = False
        lock_req = (
            self.sys_config['safety']['min_stop_minutes']
            if self.current_mode == "LOW"
            else self.sys_config['safety']['min_run_minutes']
        )
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

        # === 4. CHW / VRF load split ===
        chiller_num = self.sys_config['equipment']['chiller_total_units']
        _unit_caps = self.chiller_optimizer.unit_caps_kw
        _unit_cumcaps = [sum(_unit_caps[:k+1]) for k in range(len(_unit_caps))]
        # The heterogeneous unit list is the source of truth; cap_c_single
        # for legacy diagnostics is intentionally not retained here.
        c_min = self.sys_config['safety']['central_min_plr']
        q_public = 0.0
        q_private = 0.0
        desired_chillers = 0
        force_low = False
        _opt_res: dict = self.chiller_optimizer._zero_result()

        if self.current_mode != "LOW":
            if self.current_mode == "HIGH":
                q_public = sum(zone_loads_dyn[z] for z in self.zones if self.zone_can_use_chw(z))
            elif self.current_mode == "MID":
                q_public = sum(
                    zone_loads_dyn[z] for z in self.zones
                    if self.zone_can_use_chw(z) and (
                        self.zone_specs[z]["area_type"] == "公共"
                        or not self.zone_can_use_vrf(z)
                    )
                )

            desired_chillers = 0
            for _k in range(chiller_num):
                desired_chillers = _k + 1
                if _unit_cumcaps[_k] >= q_public:
                    break
            desired_chillers = min(desired_chillers, chiller_num)

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
                _min_single = _unit_caps[0] * c_min
                if q_public < _min_single and not safety_override:
                    cmd["alarms"].append(
                        "水冷系统负荷过低，存在喘振风险，系统切回低负荷模式"
                    )
                    force_low = True

        if self.current_mode == "LOW" or force_low:
            q_public = 0.0
            if force_low:
                q_private = sum(zone_loads_dyn[z] for z in self.zones if self.zone_can_use_vrf(z))
                chw_only_load = sum(
                    zone_loads_dyn[z] for z in self.zones
                    if self.zone_can_use_chw(z) and not self.zone_can_use_vrf(z)
                )
                if chw_only_load > 0:
                    cmd["alarms"].append(
                        "强制回退导致纯水系统区域无法由VRF代偿，进入温漂观察"
                    )
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
            q_private = sum(
                zone_loads_dyn[z] for z in self.zones
                if not self.zone_can_use_chw(z) and self.zone_can_use_vrf(z)
            )
        elif self.current_mode == "MID":
            q_private = sum(
                zone_loads_dyn[z] for z in self.zones
                if self.zone_can_use_vrf(z) and (
                    self.zone_specs[z]["area_type"] == "私域"
                    or not self.zone_can_use_chw(z)
                )
            )

        # === 5. CHW hydraulic recompute ===
        cooling_distribution: dict[str, float] = {}
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

        for i, z in enumerate(list(self.zones.keys())):
            if self.zone_can_use_chw(z) and cooling_distribution.get(z, 0.0) > 0:
                cmd[f"BACnet_BO_500{i+1}_Valve_{z[:2]}"] = 1
                cmd[f"BACnet_BI_510{i+1}_Valve_{z[:2]}_FB"] = 1
            else:
                cmd[f"BACnet_BO_500{i+1}_Valve_{z[:2]}"] = 0
                cmd[f"BACnet_BI_510{i+1}_Valve_{z[:2]}_FB"] = 0

        # === 6. Equipment power (incl. SLSQP optimization) ===
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

        if self.current_mode == "LOW":
            combo, mech = "LOW", "多联机独立运转"
            if q_private > cap_v:
                cmd["alarms"].append(
                    f"多联机需求超过容量上限: {cap_v:.1f}kW，已限幅"
                )
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
                    cmd["alarms"].append(
                        "极低负荷区域，机组进入深度待机 (不计节能收益)"
                    )
                    self.log_event("极低负荷保护", "多联机系统挂起")
                    q_private = 0.0
                    cmd["BACnet_AO_4001_VRF_Demand_kW"] = 0.0
            elif q_private > 0:
                cmd["BACnet_AO_4001_VRF_Demand_kW"] = round(q_private, 1)

            if q_private > 0:
                cop_v = self.registry.get('vrf').calculate_cop(
                    t_out, max(v_min, q_private / cap_v),
                    self.sys_config, self.log_event, cmd["alarms"],
                )
                P_v = q_private / cop_v
                q_delivered = q_private
                cmd["BACnet_BI_4002_VRF_RunStatus"] = 1

        else:
            if desired_chillers != self.current_chillers:
                if (
                    self.time_in_staging >= self.sys_config['safety']['staging_lock_minutes']
                    or safety_override
                ):
                    self.current_chillers = desired_chillers
                    self.time_in_staging = 0
                else:
                    desired_chillers = self.current_chillers
                    cmd["alarms"].append(
                        f"冷机加减机防抖锁定中: 当前 {self.current_chillers} 台"
                    )
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
                        t_out, max(v_min, q_private / cap_v),
                        self.sys_config, self.log_event, cmd["alarms"],
                    )
                    P_v = q_private / cop_v

            if self.current_mode == "HIGH" and q_private > 0:
                if cap_v > 0:
                    cop_v = self.registry.get('vrf').calculate_cop(
                        t_out, max(v_min, q_private / cap_v),
                        self.sys_config, self.log_event, cmd["alarms"],
                    )
                    P_v = q_private / cop_v
                    cmd["BACnet_BI_4002_VRF_RunStatus"] = 1

            if q_public > 0 and desired_chillers > 0:
                _t_chw = hydraulic_info.get("supply_temp_c", 7.0)
                _t_cw = max(28.0, min(38.0, t_out - 8.0))
                _opt_res = self.chiller_optimizer.optimize(
                    q_total_kw=q_public,
                    t_out=t_out,
                    n_active=desired_chillers,
                    t_cw=_t_cw,
                    t_chw=_t_chw,
                    alarms_list=cmd["alarms"],
                )
                P_c = _opt_res['total_power_kw']
                cop_c = _opt_res['system_cop'] if _opt_res['system_cop'] > 0 else 4.0
                plr_c = (
                    q_public / sum(_unit_caps[:desired_chillers])
                    if sum(_unit_caps[:desired_chillers]) > 0 else 0.0
                )
                self.log_event(
                    "群控寻优",
                    "[{s}] 需求={q:.0f}kW "
                    "CH1:{l1:.0f}|CH2:{l2:.0f}|CH3:{l3:.0f} kW "
                    "→ 总功耗={p:.1f}kW 系统COP={c:.3f} "
                    "T_cw={tcw:.1f}℃ T_chw={tchw:.1f}℃".format(
                        s=_opt_res['status'], q=q_public,
                        l1=_opt_res['loads'][0], l2=_opt_res['loads'][1],
                        l3=_opt_res['loads'][2],
                        p=P_c, c=cop_c, tcw=_t_cw, tchw=_t_chw,
                    ),
                )

            q_delivered = q_public + q_private

        pump_p = hydraulic_info.get("pump_power_kw", 0.0)
        opt_p = P_c + P_v + pump_p
        self.sim_time += dt

        # === 7. Transformer protection ===
        limit_kw = (
            self.sys_config['safety']['transformer_capacity_kva']
            * self.sys_config['safety']['power_factor']
        )
        if opt_p > limit_kw:
            excess = opt_p - limit_kw
            cmd['shedding_seq'].append(
                f"变压器容量越限保护 {excess:.1f}kW，启动减载:"
            )
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

        # === 8. Indoor temperature update + economics ===
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
                self.log_event(
                    "容量越限",
                    f"强制减载，供冷满足率 {cooling_satisfaction*100:.1f}%",
                )
            else:
                satisfaction_disp = "设备满载能力受限 (不计收益)"
                self.log_event(
                    "满载边界",
                    f"供冷满足率 {cooling_satisfaction*100:.1f}%",
                )
        else:
            rate = round((trad_p - opt_p) / trad_p, 4) if trad_p > 0 else 0.0
            saved_kw = max(0.0, trad_p - opt_p)
            satisfaction_disp = (
                f"达标 {min(100.0, round(cooling_satisfaction * 100, 1))}%"
            )
            rate_disp = f"{round(rate * 100, 2)}%"
            satisfaction_val = cooling_satisfaction

        if accumulate_lcc and saved_kw > 0:
            self.lcc.add_kwh(saved_kw, dt, self.sim_time)

        # === 9. Result assembly + state restore ===
        active_cop = round(q_delivered / (P_c + P_v), 2) if (P_c + P_v) > 0 else 0.0
        cmd.update({
            "Chiller_Actual_Power_kW": round(P_c, 1),
            "VRF_Actual_Power_kW": round(P_v, 1),
            "Chiller_Delivered_Cooling_kW": round(P_c * cop_c, 1) if P_c > 0 else 0.0,
            "VRF_Delivered_Cooling_kW": round(P_v * cop_v, 1) if P_v > 0 else 0.0,
        })

        chiller_status = {
            "running_units": cmd.get("BACnet_DO_3001_Chiller_Units", 0),
            "plr_percent": round(plr_c * 100, 1) if cmd.get("BACnet_DO_3001_Chiller_Units", 0) > 0 else 0.0,
            "cop": round(cop_c, 2) if cmd.get("BACnet_DO_3001_Chiller_Units", 0) > 0 else 0.0,
            "evap_flow_m3h": hydraulic_info.get("total_flow_m3h", 0.0),
            "optimizer": {
                "unit_names": list(self.chiller_optimizer.UNIT_NAMES),
                "unit_caps_kw": [round(c, 1) for c in self.chiller_optimizer.unit_caps_kw],
                "loads_kw": _opt_res.get('loads', [0.0, 0.0, 0.0]),
                "powers_kw": _opt_res.get('powers', [0.0, 0.0, 0.0]),
                "cops": _opt_res.get('cops', [0.0, 0.0, 0.0]),
                "plrs": _opt_res.get('plrs', [0.0, 0.0, 0.0]),
                "total_power_kw": _opt_res.get('total_power_kw', 0.0),
                "system_cop": _opt_res.get('system_cop', 0.0),
                "status": _opt_res.get('status', '-'),
            },
        }

        self._is_silent = prev_silent
        if not ai_info_resolved and active_strategy is not None:
            try:
                ai_info_resolved = active_strategy.get_last_info()
            except Exception:
                ai_info_resolved = None

        # ── Per-step physics frame dispatch ─────────────────────────
        physics_state: dict | None = None
        try:
            _eq = self.sys_config.get('equipment', {}) if isinstance(self.sys_config, dict) else {}
            _env_cfg = self.sys_config.get('envelope', {}) if isinstance(self.sys_config, dict) else {}
            _bldg_area = _eq.get('floor_area_m2', 12000)
            _wwr = _env_cfg.get('window_to_wall_ratio', 0.65)
            _hour = float(factor.get('hour', 12)) if isinstance(factor, dict) else 12.0
            _chw_supply = (
                hydraulic_info.get("supply_temp_c", 7.0)
                if isinstance(hydraulic_info, dict) else 7.0
            )

            physics_state = self.physics_engine.simulate_all(
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

            for cb in list(self.frame_callbacks):
                try:
                    cb(physics_state)
                except Exception:
                    _logger.exception(
                        "WhiteBoxEngine: frame_callback %r raised", cb,
                    )
        except Exception as _exc:
            try:
                self.log_event("物理过程反算异常", f"{type(_exc).__name__}: {_exc}")
            except Exception:
                pass

        return {
            "time": self.sim_time, "dt": dt,
            "load": round(q_required, 2), "delivered": round(q_delivered, 2),
            "target": round(target_load, 2),
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
            "ai_suggested_type": (
                type(active_strategy).__name__ if active_strategy is not None else "无"
            ),
            "ai_info": ai_info_resolved if ai_info_resolved else {
                "reason": "本地执行", "risk_note": "-",
                "confidence": 1.0, "fallback": False,
            },
            "safety_override": safety_override_flag,
            "hydraulic": hydraulic_info,
            "chiller_status": chiller_status,
            "sys_safety_cfg": self.sys_config['safety'],
            "mode_before": mode_before,
            "physics_state": physics_state,
        }

    # ----------------------------------------------------------- frozen
    def _frozen_state(self, ai_info: dict | None = None) -> dict:
        empty_checkpoints = {
            "chiller_out": {"T": 7.0, "P": 0.0, "F": 0.0},
            "pump_out": {"T": 7.0, "P": 0.0, "F": 0.0},
            "distributor": {"T": 7.0, "P": 0.0, "F": 0.0},
            "term_in": {"T": 7.0, "P": 0.0, "F": "--"},
            "term_out": {"T": 12.0, "P": 0.0, "F": "--"},
            "return_main": {"T": 12.0, "P": 0.0, "F": 0.0},
        }
        return {
            "time": self.sim_time, "dt": 0,
            "load": 0.0, "delivered": 0.0, "target": 0.0,
            "combo": "急停断开", "mech": "底层点位物理级挂起隔离",
            "cmd": {
                "BACnet_AV_9001_LockTimer": "锁死",
                "alarms": [], "shedding_seq": [],
                "Chiller_Actual_Power_kW": 0.0, "VRF_Actual_Power_kW": 0.0,
                "Chiller_Delivered_Cooling_kW": 0.0, "VRF_Delivered_Cooling_kW": 0.0,
            },
            "trad_p": 0.0, "opt_p": 0.0,
            "rate": 0.0, "rate_disp": "0.0%",
            "t_out": 0.0, "t_in": self.rc_model.t_in,
            "active_cop": 0.0, "is_switching": False,
            "cooling_satisfaction_val": 1.0,
            "cooling_satisfaction_disp": "急停状态，计费中止",
            "ai_requested_mode": "-",
            "ai_suggested_type": "急停断开",
            "ai_info": ai_info if ai_info else {
                "reason": "-", "risk_note": "-",
                "confidence": 0.0, "fallback": False,
            },
            "safety_override": False,
            "lcc_info": self.lcc.evaluate_annual(),
            "total_kwh_saved": self.lcc.total_kwh_saved,
            "total_cost_saved": self.lcc.total_cost_saved,
            "hydraulic": {
                "supply_temp_c": 7.0, "return_temp_c": 12.0, "delta_t_c": 5.0,
                "total_flow_m3h": 0.0, "pump_head_kpa": 0.0, "pump_head_m": 0.0,
                "pump_power_kw": 0.0, "pump_freq_hz": 0.0, "pump_speed_rpm": 0,
                "pump_vfd_percent": 0.0, "checkpoints": empty_checkpoints,
                "branches": [], "is_sleep": True,
            },
            "chiller_status": {
                "running_units": 0, "plr_percent": 0.0,
                "cop": 0.0, "evap_flow_m3h": 0.0,
            },
            "sys_safety_cfg": self.sys_config['safety'],
            "mode_before": self.current_mode,
        }


__all__ = ["WhiteBoxEngine"]
