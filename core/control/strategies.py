"""Local control strategies used by the five-layer control chain.

Two concrete strategies are provided:

* :class:`RuleBasedStrategy` -- the legacy threshold-based rule (banner-
  adjusted lines 2905-2923 of the frozen reference module under
  ``legacy/``). It picks
  ``LOW`` / ``MID`` / ``HIGH`` from the smoothed total load and the
  building's ``th`` thresholds, with one anti-surge guard for the public
  CHW share.
* :class:`MPCStrategy` -- the legacy 2-step look-ahead MPC (banner-adjusted
  lines 2925-2960) but **hardened** with explicit constructor arguments
  for horizon, dead-time, lockout penalties, switching penalty and a
  pluggable TOU price provider. The defaults match the legacy behaviour
  bit-for-bit so existing tests stay green.

The legacy cloud-LLM and fake-cloud BiLSTM control strategies are
intentionally **not** ported here -- the LLM / fake-cloud control path is
deleted by FEAT-003. A regression test (``tests/test_no_llm_in_control.py``)
enforces this.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from typing import Any


class BaseStrategy(abc.ABC):
    """Abstract local strategy.

    Subclasses must implement :meth:`decide_mode` and may override
    :meth:`get_last_info` to expose the most recent decision rationale.
    """

    @abc.abstractmethod
    def decide_mode(self, engine: Any, current_factor: dict, dt: float) -> str:
        """Return the desired mode string: 'LOW' | 'MID' | 'HIGH'."""

    def get_last_info(self) -> dict[str, Any]:
        """Free-form decision metadata; defaults are safe placeholders."""
        return {
            "reason": "本地规则执行",
            "risk_note": "无",
            "confidence": 1.0,
            "fallback": False,
        }


class RuleBasedStrategy(BaseStrategy):
    """Threshold-based rule (legacy banner-adjusted lines 2905-2923).

    Picks ``HIGH`` above the building's ``th['high']`` total load,
    ``MID`` above ``th['mid']``, with an anti-surge guard that demotes to
    ``LOW`` when the public CHW share would force the central plant
    below its minimum PLR. ``is_night`` always forces ``LOW``.
    """

    def decide_mode(self, engine: Any, current_factor: dict, dt: float) -> str:
        _, zone_loads, target_load, is_night = engine._parse_inputs(current_factor)
        if is_night:
            return "LOW"
        if target_load > engine.th.get("high", 6000.0):
            return "HIGH"
        if target_load > engine.th.get("mid", 2200.0):
            q_pub = sum(
                zone_loads[z]
                for z in engine.zones
                if engine.zone_can_use_chw(z)
                and (
                    engine.zone_specs[z]["area_type"] == "公共"
                    or not engine.zone_can_use_vrf(z)
                )
            )
            cap_c = engine.sys_config["equipment"]["capacity_central_kw"]
            c_min = engine.sys_config["safety"]["central_min_plr"]
            if q_pub > 0 and (q_pub / cap_c) < c_min:
                return "LOW"
            return "MID"
        return "LOW"

    def get_last_info(self) -> dict[str, Any]:
        return {
            "reason": "本地阈值规则控制",
            "risk_note": "-",
            "confidence": 1.0,
            "fallback": False,
        }


class MPCStrategy(BaseStrategy):
    """2-step look-ahead MPC over candidate modes (legacy 2925-2960, hardened).

    The legacy algorithm is preserved verbatim; only the magic numbers have
    been promoted to constructor arguments so operators / tests can tune
    them without monkey-patching the strategy class.

    Parameters
    ----------
    horizon : int, default 2
        Number of look-ahead steps to evaluate. The legacy default of 2
        is preserved; values >= 1 are supported. With horizon ``H`` the
        candidate cost is the sum of TOU * energy over the next ``H``
        steps plus comfort + start/stop penalties.
    dead_time_min : float, default 5.0
        Outdoor-temperature perturbation in the look-ahead candidate is
        delayed by this many minutes of simulated time. Concretely, the
        ``+0.5 degC`` perturbation only kicks in once the simulated
        elapsed time has exceeded ``dead_time_min``. The legacy code
        applied the perturbation immediately on step 2; setting
        ``dead_time_min=0`` reproduces that behaviour.
    min_run_minutes, min_stop_minutes : float or None, default None
        When supplied, override the values pulled from ``sys_config['safety']``
        on the engine. A candidate that proposes a mode switch while
        ``engine.time_in_mode`` is below the relevant lockout receives a
        ``10000``-yuan penalty. Pass ``None`` to read from sys_config.
    switch_penalty_yuan : float, default 200
        Penalty added each time a candidate exhibits a mode switch on any
        of its look-ahead steps. Replaces the hardcoded ``200`` in the
        legacy implementation.
    tou_provider : callable, optional
        ``Callable[[int hour], float yuan_per_kwh]``. When supplied, it is
        used in place of ``engine.lcc.get_price_by_hour`` for the cost
        rollup. Useful for mocking in unit tests.
    """

    DEFAULT_HORIZON: int = 2
    DEFAULT_DEAD_TIME_MIN: float = 5.0
    DEFAULT_SWITCH_PENALTY_YUAN: float = 200.0
    LOCKOUT_VIOLATION_PENALTY_YUAN: float = 10000.0
    COMFORT_PENALTY_PER_DEG: float = 5000.0
    SATISFACTION_PENALTY_YUAN: float = 2000.0
    SATISFACTION_THRESHOLD: float = 0.95

    def __init__(
        self,
        horizon: int = DEFAULT_HORIZON,
        dead_time_min: float = DEFAULT_DEAD_TIME_MIN,
        min_run_minutes: float | None = None,
        min_stop_minutes: float | None = None,
        switch_penalty_yuan: float = DEFAULT_SWITCH_PENALTY_YUAN,
        tou_provider: Callable[[int], float] | None = None,
    ) -> None:
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        self.horizon = int(horizon)
        self.dead_time_min = float(dead_time_min)
        self._override_min_run = min_run_minutes
        self._override_min_stop = min_stop_minutes
        self.switch_penalty_yuan = float(switch_penalty_yuan)
        self.tou_provider = tou_provider

    # ------------------------------------------------------------------ helpers
    def _resolve_lockout(self, engine: Any) -> tuple[float, float]:
        """Return ``(min_run_minutes, min_stop_minutes)`` for this engine.

        Constructor overrides win; otherwise read from
        ``engine.sys_config['safety']``.
        """
        safety = engine.sys_config.get("safety", {}) if hasattr(engine, "sys_config") else {}
        min_run = (
            float(self._override_min_run)
            if self._override_min_run is not None
            else float(safety.get("min_run_minutes", 0.0))
        )
        min_stop = (
            float(self._override_min_stop)
            if self._override_min_stop is not None
            else float(safety.get("min_stop_minutes", 0.0))
        )
        return min_run, min_stop

    def _price_at(self, engine: Any, hour: int) -> float:
        if self.tou_provider is not None:
            return float(self.tou_provider(int(hour)))
        return float(engine.lcc.get_price_by_hour(int(hour)))

    # ------------------------------------------------------------------ main
    def decide_mode(self, engine: Any, current_factor: dict, dt: float) -> str:
        best_mode = "LOW"
        min_cost = float("inf")
        original_state = engine.export_state()
        original_mode = engine.current_mode
        original_time_in_mode = float(getattr(engine, "time_in_mode", 0.0))

        min_run, min_stop = self._resolve_lockout(engine)

        # Pre-compute the per-step factors. Step 0 is identity; step k>=1
        # adds ``+0.5 degC`` to ``t_out`` once simulated elapsed time
        # exceeds ``dead_time_min``.
        factors: list[dict] = []
        for k in range(self.horizon):
            f_k = current_factor.copy()
            elapsed = (k + 1) * float(dt)
            if k > 0 and elapsed > self.dead_time_min:
                f_k["t_out"] = f_k.get("t_out", 33.5) + 0.5
            factors.append(f_k)

        try:
            for candidate in ("LOW", "MID", "HIGH"):
                engine.restore_state(original_state)
                results: list[dict] = []
                for f_k in factors:
                    r_k = engine.execute_step(
                        f_k,
                        forced_mode=candidate,
                        dt=dt,
                        accumulate_lcc=False,
                        silent=True,
                    )
                    results.append(r_k)

                # --- per-step monetary cost ---
                cost = 0.0
                for r_k in results:
                    h_k = int((r_k["time"] / 60) % 24)
                    cost += r_k["opt_p"] * dt / 60.0 * self._price_at(engine, h_k)

                # --- comfort + satisfaction penalties ---
                t_limit = engine.sys_config["safety"]["indoor_temp_limit"]
                penalty = 0.0
                for r_k in results:
                    if r_k["t_in"] > t_limit:
                        penalty += (r_k["t_in"] - t_limit) * self.COMFORT_PENALTY_PER_DEG
                    if r_k["cooling_satisfaction_val"] < self.SATISFACTION_THRESHOLD:
                        penalty += self.SATISFACTION_PENALTY_YUAN
                    if r_k["is_switching"]:
                        penalty += self.switch_penalty_yuan

                # --- lockout (min_run / min_stop) penalty ---
                if candidate != original_mode:
                    lockout = min_stop if original_mode == "LOW" else min_run
                    if original_time_in_mode < lockout:
                        penalty += self.LOCKOUT_VIOLATION_PENALTY_YUAN

                if cost + penalty < min_cost:
                    min_cost = cost + penalty
                    best_mode = candidate
        finally:
            engine.restore_state(original_state)
        return best_mode

    def get_last_info(self) -> dict[str, Any]:
        return {
            "reason": "本地多步预测控制(MPC)寻优",
            "risk_note": "不含长效建筑热惯性",
            "confidence": 0.95,
            "fallback": False,
        }


__all__ = ["BaseStrategy", "RuleBasedStrategy", "MPCStrategy"]
