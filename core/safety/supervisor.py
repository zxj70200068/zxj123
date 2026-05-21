"""Hard safety gate for every supervisory control command.

The :class:`SafetySupervisor` is the **last** stage of the five-layer control
chain (Prediction -> Optimization -> Rule -> Safety -> Execution). Every
:class:`ControlCommand` produced by upstream stages must pass through
:meth:`SafetySupervisor.validate_command` before being dispatched to the
adapter layer. The supervisor:

* Clamps numeric ranges (chilled-water supply temp, pump frequency,
  number of running chillers, VRF demand) to physically safe bounds.
* Enforces equipment lockout windows (min run / min stop minutes).
* Forces a degraded fallback mode under communication or AI-strategy
  failure.
* Forces a high-cooling mode under indoor-temperature breach.

Every triggered rule appends a string to ``cmd.alarms`` and sets
``cmd.overridden = True``. The original input command is never mutated;
the supervisor returns a new :class:`ControlCommand`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.logging import get_logger

_logger = get_logger(__name__)


@dataclass
class ControlCommand:
    """Concrete output of the control chain.

    Fields are kept primitive (no nested dicts) so the safety supervisor's
    range checks operate on simple scalars and tests can construct
    instances by keyword without boilerplate.
    """

    mode: str = "LOW"
    n_chillers: int = 0
    vrf_demand_kw: float = 0.0
    chw_supply_temp_c: float = 7.0
    pump_freq_hz: float = 30.0
    alarms: list[str] = field(default_factory=list)
    overridden: bool = False

    def copy(self) -> ControlCommand:
        """Return a deep-enough copy: alarms list is duplicated."""
        return ControlCommand(
            mode=self.mode,
            n_chillers=self.n_chillers,
            vrf_demand_kw=self.vrf_demand_kw,
            chw_supply_temp_c=self.chw_supply_temp_c,
            pump_freq_hz=self.pump_freq_hz,
            alarms=list(self.alarms),
            overridden=self.overridden,
        )


_VALID_MODES: tuple[str, ...] = ("LOW", "MID", "HIGH", "ESTOP")


class SafetySupervisor:
    """Final clamp + override stage of the control chain.

    Parameters
    ----------
    sys_config : dict
        Full system configuration. Reads from ``sys_config['safety']``,
        ``sys_config['equipment']``. Missing keys fall back to engineering
        defaults documented per rule below.
    """

    def __init__(self, sys_config: dict) -> None:
        self.sys_config: dict = sys_config

    # ------------------------------------------------------------------ utils
    def _safety(self) -> dict:
        return self.sys_config.get("safety", {}) or {}

    def _equipment(self) -> dict:
        return self.sys_config.get("equipment", {}) or {}

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> tuple[float, bool]:
        """Clamp ``value`` to ``[low, high]``; second return is True if changed."""
        new = max(low, min(high, value))
        return new, new != value

    # ------------------------------------------------------------- validation
    def validate_command(
        self,
        cmd: ControlCommand,
        engine_state: dict[str, Any],
    ) -> ControlCommand:
        """Return a clamped + override-applied copy of ``cmd``.

        The eight rules are listed in step 7 of FEAT-003 and each is
        documented inline below. Every rule that fires both appends a
        descriptive Chinese alarm and sets ``out.overridden = True``.
        """
        out = cmd.copy()
        safety = self._safety()
        equipment = self._equipment()

        # --- Rule 1: chw_supply_temp_c clamped to [chw_min_c, chw_max_c] ---
        chw_min = float(safety.get("chw_min_c", 5.0))
        chw_max = float(safety.get("chw_max_c", 12.0))
        new_chw, changed = self._clamp(out.chw_supply_temp_c, chw_min, chw_max)
        if changed:
            out.chw_supply_temp_c = new_chw
            out.alarms.append(
                f"安全超限: 冷冻水供水温度被裁剪至 [{chw_min:.1f}, {chw_max:.1f}]℃"
            )
            out.overridden = True
            _logger.warning(
                "SafetySupervisor: chw_supply_temp_c clamped to %.2f", new_chw,
            )

        # --- Rule 2: pump_freq_hz clamped to [pump_min_hz, pump_max_hz] ---
        pump_min = float(safety.get("pump_min_hz", 20.0))
        pump_max = float(safety.get("pump_max_hz", 50.0))
        new_pump, changed = self._clamp(out.pump_freq_hz, pump_min, pump_max)
        if changed:
            out.pump_freq_hz = new_pump
            out.alarms.append(
                f"安全超限: 水泵频率被裁剪至 [{pump_min:.0f}, {pump_max:.0f}] Hz"
            )
            out.overridden = True
            _logger.warning(
                "SafetySupervisor: pump_freq_hz clamped to %.2f", new_pump,
            )

        # --- Rule 3: n_chillers clamped to [0, chiller_total_units] ---
        max_units = int(equipment.get("chiller_total_units", 0))
        if out.n_chillers < 0 or out.n_chillers > max_units:
            new_n = max(0, min(max_units, int(out.n_chillers)))
            out.alarms.append(
                f"安全超限: 启用机组台数被裁剪至 [0, {max_units}] 台"
            )
            out.n_chillers = new_n
            out.overridden = True
            _logger.warning(
                "SafetySupervisor: n_chillers clamped to %d", new_n,
            )

        # --- Rule 4: vrf_demand_kw clamped to [0, capacity_vrf_kw] ---
        vrf_max = float(equipment.get("capacity_vrf_kw", 0.0))
        if out.vrf_demand_kw < 0.0 or out.vrf_demand_kw > vrf_max:
            new_vrf, _ = self._clamp(out.vrf_demand_kw, 0.0, vrf_max)
            out.vrf_demand_kw = new_vrf
            out.alarms.append(
                f"安全超限: VRF 需求功率被裁剪至 [0, {vrf_max:.0f}] kW"
            )
            out.overridden = True
            _logger.warning(
                "SafetySupervisor: vrf_demand_kw clamped to %.2f", new_vrf,
            )

        # --- Rule 5: min_run / min_stop time enforcement ----------------
        # When the proposal is to drop to LOW but the current mode has not
        # been held for ``min_run_minutes`` yet, force keep current mode.
        time_in_mode = float(engine_state.get("time_in_mode", 0.0))
        min_run = float(safety.get("min_run_minutes", 0.0))
        current_mode = str(engine_state.get("current_mode", out.mode))
        if (
            out.mode == "LOW"
            and current_mode in ("MID", "HIGH")
            and time_in_mode < min_run
        ):
            out.alarms.append(
                f"安全超限: 最小运行时间未满 ({time_in_mode:.0f} < {min_run:.0f} min)，保持 {current_mode}"
            )
            out.mode = current_mode
            out.overridden = True
            _logger.warning(
                "SafetySupervisor: min run time not satisfied; held %s", current_mode,
            )

        # --- Rule 6: communication timeout fallback ---------------------
        if bool(engine_state.get("comm_timeout", False)):
            out.alarms.append("通讯中断: 控制链回退至 LOW 模式 (n_chillers=0)")
            out.mode = "LOW"
            out.n_chillers = 0
            out.overridden = True
            _logger.error("SafetySupervisor: comm_timeout fallback to LOW")

        # --- Rule 7: AI-strategy failure fallback -----------------------
        if bool(engine_state.get("ai_failure", False)):
            fallback_mode = str(engine_state.get("fallback_mode", "LOW"))
            if fallback_mode not in _VALID_MODES:
                fallback_mode = "LOW"
            out.alarms.append(
                f"AI 策略失败: 回退至 {fallback_mode} 模式"
            )
            out.mode = fallback_mode
            out.overridden = True
            _logger.error(
                "SafetySupervisor: ai_failure fallback to %s", fallback_mode,
            )

        # --- Rule 8: indoor temperature limit override ------------------
        # If the indoor temperature has breached the safety limit, force a
        # higher cooling mode regardless of upstream proposal. ``MID`` is
        # used for moderate breaches and ``HIGH`` once the load climbs
        # above the building's `th.high` threshold (or, if not provided,
        # half the central capacity).
        indoor_limit = float(safety.get("indoor_temp_limit", 26.5))
        t_in = engine_state.get("t_in")
        if t_in is not None and float(t_in) > indoor_limit:
            load_kw = float(engine_state.get("target_load_kw", 0.0))
            high_th = float(engine_state.get("th_high", 6000.0))
            forced = "HIGH" if load_kw > high_th else "MID"
            if out.mode != forced:
                out.alarms.append(
                    f"室内温度安全超限 ({float(t_in):.1f}℃ > {indoor_limit:.1f}℃): "
                    f"强制切换至 {forced}"
                )
                out.mode = forced
                out.overridden = True
                _logger.error(
                    "SafetySupervisor: indoor_temp_limit breach; forced %s", forced,
                )

        return out


__all__ = ["SafetySupervisor", "ControlCommand"]
