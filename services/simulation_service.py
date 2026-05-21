"""Simulation orchestrator.

This service is the **single** entry point UI / batch / CLI callers use to
drive the white-box simulation engine. It instantiates and caches one
:class:`core.simulation.engine.WhiteBoxEngine` per ``building_key`` and
hides the strategy/supervisor/predictor wiring behind two methods:

* :meth:`run_single_step` -- one ``execute_step`` call with an explicit
  scenario factor.
* :meth:`run_sequence` -- iterate a sequence plan (list of
  ``{'scenario': ..., 'steps': N}`` entries) and return the flat list of
  step results.

The service intentionally has **no** Tkinter imports, no per-step Tk
side effects, and never returns engine internals: the caller only sees
plain Python dicts (the same shape ``WhiteBoxEngine.execute_step`` already
returns).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.config import ConfigManager
from core.control.strategies import (
    BaseStrategy,
    MPCStrategy,
    RuleBasedStrategy,
)
from core.simulation.engine import WhiteBoxEngine
from utils.logging import get_logger

_logger = get_logger(__name__)


def _build_strategy(name: str) -> BaseStrategy:
    """Return a fresh strategy instance for ``name`` ('rule' or 'mpc')."""
    key = (name or "rule").lower()
    if key == "mpc":
        return MPCStrategy()
    if key == "rule":
        return RuleBasedStrategy()
    _logger.warning(
        "SimulationService: unknown strategy_name=%r; falling back to 'rule'", name,
    )
    return RuleBasedStrategy()


class SimulationService:
    """Headless simulation orchestrator backed by :class:`WhiteBoxEngine`.

    Parameters
    ----------
    config_manager : ConfigManager
        Owns the ``sys_config`` / building / scenario dicts. The service
        does not mutate the manager; it only reads from it.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager = config_manager
        self._engines: dict[str, WhiteBoxEngine] = {}

    # ----------------------------------------------------------- factory
    @classmethod
    def from_defaults(cls) -> SimulationService:
        """Build a service backed by a default-configured :class:`ConfigManager`.

        UI / CLI callers use this factory so they do not have to import
        :mod:`core.config` directly. The static UI-decoupling guard
        (``tests/test_ui_decoupling.py``) treats ``core.*`` imports under
        ``ui/`` as a hard error; routing the ConfigManager construction
        through this factory preserves that boundary.
        """
        return cls(ConfigManager())

    # ------------------------------------------------------------- helpers
    def _get_engine(self, building_key: str) -> WhiteBoxEngine:
        """Lazily build and cache a WhiteBoxEngine for ``building_key``.

        Building-key lookups are tolerant of unknown keys: the underlying
        engine falls back to the first configured building when the
        requested key is missing.
        """
        if building_key not in self._engines:
            self._engines[building_key] = WhiteBoxEngine(
                self.config_manager, building_key,
            )
        return self._engines[building_key]

    # ----------------------------------------------------------- single step
    def run_single_step(
        self,
        building_key: str,
        scenario_factor: dict[str, Any],
        strategy_name: str = "rule",
        dt_min: float = 15.0,
    ) -> dict[str, Any]:
        """Execute one supervisory step and return the result dict.

        The returned dict already contains keys consumed downstream:
        ``opt_p`` (optimised plant power, kW), ``t_in`` (room temperature),
        ``cmd`` (a dict with ``alarms`` list, BACnet mirror, etc.), plus
        diagnostics (``hydraulic``, ``chiller_status``, ``lcc_info``).
        """
        engine = self._get_engine(building_key)
        strategy = _build_strategy(strategy_name)
        return engine.execute_step(
            scenario_factor or {},
            strategy=strategy,
            dt=float(dt_min),
        )

    # --------------------------------------------------------------- sequence
    def run_sequence(
        self,
        building_key: str,
        sequence_plan: list[dict[str, Any]],
        strategy_name: str = "mpc",
        dt_min: float = 15.0,
        on_step: Callable[[dict[str, Any]], None] | None = None,
        on_frame: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Replay a sequence plan and collect per-step result dicts.

        Each entry of ``sequence_plan`` must have ``scenario`` (a key into
        ``config_manager.scenarios``) and ``steps`` (a positive integer).
        Unknown scenarios are skipped with a warning; the service never
        raises into the caller.

        Parameters
        ----------
        on_step : callable, optional
            Invoked once per simulation step with the full result dict
            (the same dict that is appended to the returned list). Lets a
            UI layer refresh dashboards "边跑边刷" without waiting for the
            sequence to finish. Exceptions raised inside the callback are
            logged and swallowed so a buggy UI cannot stall the sim.
        on_frame : callable, optional
            Registered on :attr:`WhiteBoxEngine.frame_callbacks` for the
            duration of this run. Called once per step with the
            per-step physics frame produced by
            :class:`core.physics.simulation_engine.PhysicsSimulationEngine`.
            The callback is removed when the sequence completes (success
            or failure) so subsequent calls without ``on_frame`` do not
            keep stale subscribers.
        """
        engine = self._get_engine(building_key)
        strategy = _build_strategy(strategy_name)
        scenarios = self.config_manager.scenarios

        if on_frame is not None:
            engine.frame_callbacks.append(on_frame)

        results: list[dict[str, Any]] = []
        try:
            for entry in sequence_plan or []:
                s_name = entry.get("scenario")
                steps = int(entry.get("steps", 0))
                if s_name not in scenarios or steps <= 0:
                    _logger.warning(
                        "SimulationService.run_sequence: skipping invalid entry %r",
                        entry,
                    )
                    continue
                factor = scenarios[s_name]
                for _ in range(steps):
                    res = engine.execute_step(
                        factor,
                        strategy=strategy,
                        dt=float(dt_min),
                    )
                    results.append(res)
                    if on_step is not None:
                        try:
                            on_step(res)
                        except Exception:
                            _logger.exception(
                                "SimulationService.run_sequence: on_step "
                                "callback raised; continuing"
                            )
        finally:
            if on_frame is not None:
                try:
                    engine.frame_callbacks.remove(on_frame)
                except ValueError:
                    pass
        return results


__all__ = ["SimulationService"]
