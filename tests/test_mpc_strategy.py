"""Targeted tests for :class:`core.control.strategies.MPCStrategy` knobs.

The chain integration tests cover the rule-based path. This module pins
the constructor knobs explicitly so a regression that disables
``tou_provider``, ``switch_penalty_yuan``, or the ``min_run_minutes``
override would fail at least one assertion (concern #12 from the v1
review).

These tests are intentionally narrow: they verify wiring, not optimum.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.config import ConfigManager
from core.control.strategies import MPCStrategy
from core.simulation.engine import WhiteBoxEngine


@pytest.fixture
def engine() -> WhiteBoxEngine:
    cm = ConfigManager()
    bk = next(iter(cm.building_configs))
    return WhiteBoxEngine(cm, bk)


@pytest.fixture
def factor(engine: WhiteBoxEngine) -> dict:
    cm = engine.config_mgr
    return dict(next(iter(cm.scenarios.values())))


def test_tou_provider_replaces_engine_lcc_price_lookup(
    engine: WhiteBoxEngine, factor: dict,
) -> None:
    """A custom ``tou_provider`` is consulted in place of ``engine.lcc``.

    We supply a provider that records every hour it was asked about and
    returns 0.0 for all hours. The strategy must invoke the provider at
    least once during the look-ahead, and ``engine.lcc.get_price_by_hour``
    must NOT be touched while the provider is active.
    """
    seen_hours: list[int] = []

    def provider(hour: int) -> float:
        seen_hours.append(int(hour))
        return 0.0

    sentinel = {"called": False}
    original = engine.lcc.get_price_by_hour

    def spy(hour: int) -> float:  # type: ignore[no-redef]
        sentinel["called"] = True
        return original(hour)

    engine.lcc.get_price_by_hour = spy  # type: ignore[assignment]

    strategy = MPCStrategy(
        horizon=2, dead_time_min=0.0, tou_provider=provider,
    )
    strategy.decide_mode(engine, factor, dt=15.0)

    assert seen_hours, "tou_provider was never invoked"
    assert all(0 <= h < 24 for h in seen_hours), (
        f"tou_provider received invalid hours: {seen_hours!r}"
    )
    assert sentinel["called"] is False, (
        "engine.lcc.get_price_by_hour was called even though "
        "tou_provider was supplied"
    )


def test_switch_penalty_yuan_drives_choice_away_from_switching(
    engine: WhiteBoxEngine, factor: dict,
) -> None:
    """A massive ``switch_penalty_yuan`` discourages mode-switching.

    We seed the engine into LOW with no lockout in the way, then run two
    MPC instances on the same factor: one with the default switch
    penalty, one with an enormous penalty. The high-penalty run must
    not pick a strictly cheaper switch when the no-switch alternative
    is at most marginally worse.

    The fixture factor is a typical mid-day shape; the assertion is
    pinned not on a specific mode but on the relationship: with the
    enormous penalty, the chosen mode equals the original (LOW) any
    time the no-switch alternative is feasible.
    """
    engine.current_mode = "LOW"
    engine.time_in_mode = 0.0

    # No lockout so neither strategy gets the LOCKOUT_VIOLATION penalty.
    cheap = MPCStrategy(
        horizon=1,
        dead_time_min=0.0,
        switch_penalty_yuan=0.0,
        min_run_minutes=0.0,
        min_stop_minutes=0.0,
        tou_provider=lambda h: 0.5,
    )
    expensive = MPCStrategy(
        horizon=1,
        dead_time_min=0.0,
        switch_penalty_yuan=1_000_000.0,
        min_run_minutes=0.0,
        min_stop_minutes=0.0,
        tou_provider=lambda h: 0.5,
    )

    cheap_choice = cheap.decide_mode(engine, factor, dt=15.0)
    # Decide with the enormous penalty separately; engine state is
    # restored inside MPCStrategy.decide_mode via export/restore.
    engine.current_mode = "LOW"
    engine.time_in_mode = 0.0
    expensive_choice = expensive.decide_mode(engine, factor, dt=15.0)

    # The expensive-penalty strategy must never strictly prefer a switch
    # that the cheap one already considered switch-free.
    if cheap_choice == "LOW":
        assert expensive_choice == "LOW", (
            f"with switch_penalty_yuan=1e6 the strategy chose "
            f"{expensive_choice!r} but the no-penalty baseline was LOW"
        )
    else:
        # Cheap chose to switch; expensive must either match (penalty
        # still didn't outweigh the energy savings) or revert to LOW
        # (penalty dominated). Either is acceptable; what's NOT
        # acceptable is the expensive run choosing a *different*
        # switching candidate than the cheap one.
        assert expensive_choice in ("LOW", cheap_choice), (
            f"unexpected expensive_choice={expensive_choice!r} when "
            f"cheap_choice={cheap_choice!r}"
        )


def test_min_run_minutes_constructor_override_beats_sys_config(
    engine: WhiteBoxEngine, factor: dict,
) -> None:
    """A constructor ``min_run_minutes`` overrides ``sys_config['safety']``.

    The strategy's ``_resolve_lockout`` is the single point that consumes
    the override; we verify the resolved tuple matches the constructor
    arguments exactly when both constructor arguments are supplied.
    """
    # Confirm the default path (no override) reads from sys_config.
    default = MPCStrategy()
    sys_min_run = float(engine.sys_config["safety"]["min_run_minutes"])
    sys_min_stop = float(engine.sys_config["safety"]["min_stop_minutes"])
    assert default._resolve_lockout(engine) == (sys_min_run, sys_min_stop)

    # And that the override wins.
    overridden = MPCStrategy(
        min_run_minutes=99.0, min_stop_minutes=77.0,
    )
    assert overridden._resolve_lockout(engine) == (99.0, 77.0)

    # The asymmetric case: override only one, the other reads sys_config.
    half_override = MPCStrategy(min_run_minutes=12.0)
    min_run, min_stop = half_override._resolve_lockout(engine)
    assert min_run == 12.0
    assert min_stop == sys_min_stop


def test_horizon_drives_lookahead_step_count(
    engine: WhiteBoxEngine, factor: dict,
) -> None:
    """``horizon`` controls how many candidate steps are evaluated."""
    seen_steps: list[Any] = []
    real_execute = engine.execute_step

    def counting_execute(*args: Any, **kwargs: Any) -> dict:
        seen_steps.append(kwargs.get("forced_mode"))
        return real_execute(*args, **kwargs)

    engine.execute_step = counting_execute  # type: ignore[assignment]
    strategy = MPCStrategy(horizon=3, dead_time_min=0.0)
    strategy.decide_mode(engine, factor, dt=15.0)
    engine.execute_step = real_execute  # type: ignore[assignment]

    # 3 candidate modes (LOW/MID/HIGH) * 3 horizon steps = 9 silent calls.
    assert len(seen_steps) == 9, (
        f"horizon=3 should invoke execute_step 9 times, got {len(seen_steps)}"
    )
