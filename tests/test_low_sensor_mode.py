"""Tests for :class:`core.control.low_sensor_mode.LowSensorMode`.

The lift must produce a fully-populated, control-chain-ready dict from a
thin observation, never raise on missing fields, and flag the result as
``is_low_sensor=True``.
"""

from __future__ import annotations

import json

from core.control.low_sensor_mode import LowSensorMode
from data.configs.defaults import DEFAULT_SYS_CONFIG


def _sys_config() -> dict:
    return json.loads(DEFAULT_SYS_CONFIG)


def test_lift_minimal_observation_produces_low_sensor_state() -> None:
    """A minimal obs (no zone_temps) still lifts to a usable state."""
    mode = LowSensorMode(_sys_config())
    obs = {
        "chw_supply_c": 7.0,
        "chw_return_c": 12.0,
        "chiller_power_kw": 600.0,
        "t_out": 33.0,
        "hour": 14,
    }
    state = mode.lift(obs)

    assert state["is_low_sensor"] is True
    assert state["target_load_kw"] > 0.0
    # Aggregate indoor temperature defaults to 24.0 when zone_temps is missing.
    assert state["t_in"] == 24.0
    # Hour propagates through and is normalised to [0, 24).
    assert 0.0 <= state["hour"] < 24.0
    # Safety-supervisor lookup keys exist with safe defaults.
    assert state["comm_timeout"] is False
    assert state["ai_failure"] is False
    assert state["current_mode"] == "LOW"


def test_lift_missing_zone_temps_does_not_raise() -> None:
    mode = LowSensorMode(_sys_config())
    state = mode.lift({})
    assert state["is_low_sensor"] is True
    assert state["target_load_kw"] >= 0.0
    assert "zone_loads_kw" in state


def test_lift_zone_temps_aggregate_indoor_temperature() -> None:
    mode = LowSensorMode(_sys_config())
    obs = {
        "chiller_power_kw": 800.0,
        "t_out": 32.0,
        "hour": 13,
        "zone_temps": {"hall": 25.0, "office": 24.0, "server": 26.0},
    }
    state = mode.lift(obs)
    assert state["is_low_sensor"] is True
    # Mean of {25, 24, 26} = 25.0.
    assert abs(state["t_in"] - 25.0) < 1e-6
    # When no zone_design overrides are in sys_config, the lift falls back
    # to an equal-share distribution across the reported zone_temps keys.
    assert set(state["zone_loads_kw"].keys()) == {"hall", "office", "server"}


def test_lift_tolerates_garbage_input_types() -> None:
    """Non-numeric strings, ``None`` values and a non-dict zone_temps must
    all be tolerated without raising."""
    mode = LowSensorMode(_sys_config())
    obs = {
        "chw_supply_c": "not-a-float",
        "chw_return_c": None,
        "chiller_power_kw": "abc",
        "t_out": None,
        "hour": "noon",
        "zone_temps": [25, 26],  # wrong type
    }
    state = mode.lift(obs)
    assert state["is_low_sensor"] is True
    assert state["t_in"] == 24.0
    assert state["target_load_kw"] >= 0.0
