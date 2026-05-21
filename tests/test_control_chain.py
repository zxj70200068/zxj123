"""Tests for :class:`core.control.control_chain.ControlChain`.

The chain is exercised without the full :class:`WhiteBoxEngine`: a fake
``engine_state`` dict drives the rule fallback, the safety supervisor is
constructed from a tiny ``sys_config``, and a real
:class:`RuleBasedStrategy` is supplied (the chain skips the strategy when
no engine context is present).
"""

from __future__ import annotations

from core.control.control_chain import ControlChain
from core.control.strategies import RuleBasedStrategy
from core.safety.supervisor import SafetySupervisor


def _sys_config() -> dict:
    return {
        "safety": {
            "chw_min_c": 5.0,
            "chw_max_c": 12.0,
            "pump_min_hz": 20.0,
            "pump_max_hz": 50.0,
            "min_run_minutes": 25,
            "min_stop_minutes": 15,
            "indoor_temp_limit": 26.5,
            "central_min_plr": 0.15,
        },
        "equipment": {
            "chiller_total_units": 3,
            "capacity_central_kw": 7140.0,
            "capacity_vrf_kw": 4000.0,
        },
    }


def _benign_state() -> dict:
    return {
        "current_mode": "LOW",
        "time_in_mode": 60.0,
        "t_in": 24.0,
        "t_out": 30.0,
        "hour": 12.0,
        "is_night": False,
        "target_load_kw": 1000.0,
        "th_high": 6000.0,
        "th_mid": 2200.0,
        "comm_timeout": False,
        "ai_failure": False,
        "vrf_demand_kw": 800.0,
        "chw_supply_temp_c": 7.0,
        "pump_freq_hz": 30.0,
    }


def test_control_chain_benign_returns_low_without_overrides() -> None:
    chain = ControlChain()
    sup = SafetySupervisor(_sys_config())
    cmd = chain.step(
        engine_state=_benign_state(),
        sys_config=_sys_config(),
        strategy=RuleBasedStrategy(),
        supervisor=sup,
        predictor=None,
    )
    assert cmd.mode == "LOW"
    assert cmd.n_chillers == 0
    assert cmd.overridden is False
    assert cmd.alarms == []


def test_control_chain_mid_load_proposes_mid_mode() -> None:
    chain = ControlChain()
    sup = SafetySupervisor(_sys_config())
    state = _benign_state() | {"target_load_kw": 3500.0}
    cmd = chain.step(
        engine_state=state,
        sys_config=_sys_config(),
        strategy=RuleBasedStrategy(),
        supervisor=sup,
        predictor=None,
    )
    assert cmd.mode == "MID"
    assert cmd.n_chillers >= 1
    assert cmd.overridden is False


def test_control_chain_comm_timeout_collapses_to_low() -> None:
    chain = ControlChain()
    sup = SafetySupervisor(_sys_config())
    # High proposal that the safety layer must override down to LOW.
    state = _benign_state() | {
        "target_load_kw": 8000.0,
        "comm_timeout": True,
    }
    cmd = chain.step(
        engine_state=state,
        sys_config=_sys_config(),
        strategy=RuleBasedStrategy(),
        supervisor=sup,
        predictor=None,
    )
    assert cmd.mode == "LOW"
    assert cmd.n_chillers == 0
    assert cmd.overridden is True
    assert any("通讯中断" in a for a in cmd.alarms)
