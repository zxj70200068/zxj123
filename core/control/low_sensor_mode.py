"""Degraded-input "low-sensor mode" lifter.

When the BAS / sensor stack is partially offline (e.g. a flow meter is
malfunctioning, the secondary supply temperature probe has dropped out),
the control chain still needs a coherent ``engine_state`` dict to act on.
:class:`LowSensorMode` performs that lift: a minimal ``observation``
containing only the chiller power and a few water/air temperatures is
expanded into a fully-populated state dict compatible with
:meth:`core.control.control_chain.ControlChain.step`.

Design contract
---------------
* The lift **never** raises. Missing fields fall back to documented
  defaults; failures are logged at WARNING level via :func:`utils.logging`.
* The output dict carries ``is_low_sensor=True`` so the safety supervisor
  and the operator UI can flag the degraded path.
* When zone-level breakdown is missing, the cooling load is distributed
  proportional to each zone's ``design_load_kw`` from sys_config.

Note
----
``is_low_sensor`` is currently an **observability-only** flag. The
:class:`core.safety.supervisor.SafetySupervisor` and
:class:`core.control.control_chain.ControlChain` do not branch on it
today; downstream operator dashboards and HistoryLogger rows consume it
to surface the degraded path. Future work may use it to relax / tighten
threshold rules (concern #8 from the v1 review).
"""

from __future__ import annotations

from typing import Any

from utils.logging import get_logger

_logger = get_logger(__name__)


def _design_cop_mid(sys_config: dict[str, Any]) -> float:
    """Pull a representative central-chiller design COP from sys_config.

    Uses the middle entry of the central COP table as a robust fallback;
    if the table is missing or malformed, returns 5.0 (a typical magnetic-
    bearing chiller mid-load COP).
    """
    try:
        central = sys_config["cop_tables"]["central"]
        # central[i] is a list across PLR for a given T_out;
        # take the middle T_out row and middle PLR column.
        mid_t = central[len(central) // 2]
        return float(mid_t[len(mid_t) // 2])
    except Exception:
        _logger.warning(
            "LowSensorMode: cop_tables.central missing/malformed; "
            "using fallback design COP=5.0"
        )
        return 5.0


def _zone_design_loads(sys_config: dict[str, Any]) -> dict[str, float]:
    """Return ``{zone_name: design_load_kw}``; tolerates missing keys."""
    out: dict[str, float] = {}
    try:
        # ``sys_config`` may not carry the zone breakdown directly when the
        # caller has passed only the global system config. ``zone_design``
        # is the optional override key consumed here.
        for zone, val in (sys_config.get("zone_design") or {}).items():
            if isinstance(val, (int, float)) and val > 0:
                out[str(zone)] = float(val)
    except Exception:
        _logger.warning(
            "LowSensorMode: zone_design lookup failed; falling back to empty",
        )
    return out


class LowSensorMode:
    """Lift a thin sensor observation into a control-chain-ready state.

    Parameters
    ----------
    sys_config : dict
        Full system configuration. The lift reads ``cop_tables.central``
        (for the design COP fallback) and the optional ``zone_design``
        breakdown for the zone proration step.
    """

    DEFAULT_DELTA_T_C: float = 5.0

    def __init__(self, sys_config: dict[str, Any]) -> None:
        self.sys_config = sys_config
        self._design_cop = _design_cop_mid(sys_config)

    # ------------------------------------------------------------------ lift
    def lift(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Return a fully-populated engine_state dict.

        Parameters
        ----------
        observation : dict
            Recognised keys (all optional):

            * ``chw_supply_c`` -- chilled-water supply temperature [degC].
            * ``chw_return_c`` -- chilled-water return temperature [degC].
            * ``chiller_power_kw`` -- electrical input to the chiller plant
              in kW; used to estimate cooling delivered as
              ``chiller_power_kw * design_cop``.
            * ``t_out`` -- outdoor dry-bulb temperature [degC].
            * ``hour`` -- hour-of-day in [0, 24).
            * ``zone_temps`` -- ``{zone_name: t_in_degC}``. When missing,
              an aggregate ``t_in`` of 24.0 degC is used.

        Returns
        -------
        dict
            State dict with at least ``is_low_sensor``, ``target_load_kw``,
            ``zone_loads_kw``, ``t_in``, ``t_out``, ``hour`` and the safety
            supervisor lookup keys (``time_in_mode``, ``current_mode``,
            ``comm_timeout``, ``ai_failure``).
        """
        if not isinstance(observation, dict):
            _logger.warning(
                "LowSensorMode.lift: non-dict observation %r; using empty",
                observation,
            )
            observation = {}

        try:
            chw_supply_c = float(observation.get("chw_supply_c", 7.0))
        except (TypeError, ValueError):
            _logger.warning("LowSensorMode.lift: invalid chw_supply_c; default 7.0")
            chw_supply_c = 7.0
        try:
            chw_return_c = float(observation.get("chw_return_c", 12.0))
        except (TypeError, ValueError):
            _logger.warning("LowSensorMode.lift: invalid chw_return_c; default 12.0")
            chw_return_c = 12.0
        try:
            chiller_power_kw = max(0.0, float(observation.get("chiller_power_kw", 0.0)))
        except (TypeError, ValueError):
            _logger.warning("LowSensorMode.lift: invalid chiller_power_kw; default 0")
            chiller_power_kw = 0.0
        try:
            t_out = float(observation.get("t_out", 33.5))
        except (TypeError, ValueError):
            _logger.warning("LowSensorMode.lift: invalid t_out; default 33.5")
            t_out = 33.5
        try:
            hour = float(observation.get("hour", 12.0)) % 24.0
        except (TypeError, ValueError):
            _logger.warning("LowSensorMode.lift: invalid hour; default 12.0")
            hour = 12.0

        # --- Aggregate cooling load estimate ---------------------------
        # Primary: chiller_power_kw * design_cop. Secondary fallback when
        # both dT and supply-temp data are present and chiller_power is 0:
        # use a rough envelope estimate (set to chiller power * COP=4.0).
        target_load_kw = max(0.0, chiller_power_kw * self._design_cop)
        if target_load_kw == 0.0 and chiller_power_kw > 0.0:
            target_load_kw = chiller_power_kw * 4.0

        # --- Zone-level breakdown --------------------------------------
        zone_temps = observation.get("zone_temps")
        if not isinstance(zone_temps, dict):
            if zone_temps is not None:
                _logger.warning(
                    "LowSensorMode.lift: zone_temps not a dict (%r); ignoring",
                    type(zone_temps).__name__,
                )
            zone_temps = {}

        design = _zone_design_loads(self.sys_config)
        if design:
            total_design = sum(design.values()) or 1.0
            zone_loads_kw = {
                z: round(target_load_kw * (d / total_design), 2)
                for z, d in design.items()
            }
        elif zone_temps:
            # Equal-share fallback over reported zone temperatures.
            n = len(zone_temps)
            share = target_load_kw / n if n else target_load_kw
            zone_loads_kw = {z: round(share, 2) for z in zone_temps}
        else:
            zone_loads_kw = {}

        # --- Aggregate indoor temperature ------------------------------
        if zone_temps:
            try:
                t_in = float(sum(zone_temps.values()) / len(zone_temps))
            except Exception:
                _logger.warning(
                    "LowSensorMode.lift: zone_temps aggregation failed; default 24.0",
                )
                t_in = 24.0
        else:
            t_in = 24.0

        delta_t = max(1.0, chw_return_c - chw_supply_c)

        # is_night heuristic: outside the 06:00-22:00 window.
        is_night = (hour < 6.0) or (hour >= 22.0)

        return {
            "is_low_sensor": True,
            "t_out": t_out,
            "hour": hour,
            "is_night": bool(is_night),
            "t_in": round(t_in, 2),
            "chw_supply_c": chw_supply_c,
            "chw_return_c": chw_return_c,
            "chw_delta_t_c": round(delta_t, 2),
            "chiller_power_kw": chiller_power_kw,
            "target_load_kw": round(target_load_kw, 2),
            "zone_loads_kw": zone_loads_kw,
            # Safety-supervisor lookup defaults; the live engine overrides
            # these when LowSensorMode is wrapped in WhiteBoxEngine.
            "time_in_mode": 0.0,
            "current_mode": "LOW",
            "comm_timeout": False,
            "ai_failure": False,
            # Threshold defaults so the rule fallback in ControlChain works.
            "th_high": float(
                self.sys_config.get("equipment", {}).get("capacity_central_kw", 7140.0)
                * 0.85
            ),
            "th_mid": float(
                self.sys_config.get("equipment", {}).get("capacity_central_kw", 7140.0)
                * 0.30
            ),
            "c_sch": 1.0,
            "c_occ": 1.0,
        }


__all__ = ["LowSensorMode"]
