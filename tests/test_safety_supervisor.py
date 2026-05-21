"""Unit tests for :class:`core.safety.supervisor.SafetySupervisor`.

Each of the eight rules listed in FEAT-003 step 7 is exercised below with
a single out-of-range or override-triggering input plus an in-range
``benign`` reference case.
"""

from __future__ import annotations

import pytest

from core.safety.supervisor import ControlCommand, SafetySupervisor


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
        },
        "equipment": {
            "chiller_total_units": 3,
            "capacity_vrf_kw": 4000.0,
        },
    }


def _benign_state() -> dict:
    return {
        "current_mode": "MID",
        "time_in_mode": 60.0,
        "t_in": 24.5,
        "comm_timeout": False,
        "ai_failure": False,
        "target_load_kw": 2000.0,
        "th_high": 6000.0,
    }


# ---------------------------------------------------------------- benign

def test_benign_command_passes_through_unchanged() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(
        mode="MID",
        n_chillers=2,
        vrf_demand_kw=1500.0,
        chw_supply_temp_c=7.0,
        pump_freq_hz=35.0,
    )
    out = sup.validate_command(cmd, _benign_state())
    assert out.mode == "MID"
    assert out.n_chillers == 2
    assert out.vrf_demand_kw == 1500.0
    assert out.chw_supply_temp_c == 7.0
    assert out.pump_freq_hz == 35.0
    assert out.alarms == []
    assert out.overridden is False


# --------------------------------------------------------------- rules

def test_rule1_chw_supply_temp_clamped_low() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(chw_supply_temp_c=2.0, mode="MID", n_chillers=1)
    out = sup.validate_command(cmd, _benign_state())
    assert out.chw_supply_temp_c == 5.0
    assert out.overridden is True
    assert any("冷冻水供水温度" in a for a in out.alarms)


def test_rule1_chw_supply_temp_clamped_high() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(chw_supply_temp_c=15.0, mode="MID", n_chillers=1)
    out = sup.validate_command(cmd, _benign_state())
    assert out.chw_supply_temp_c == 12.0
    assert out.overridden is True


def test_rule2_pump_freq_clamped() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(pump_freq_hz=5.0, mode="MID", n_chillers=1)
    out = sup.validate_command(cmd, _benign_state())
    assert out.pump_freq_hz == 20.0
    assert out.overridden is True
    assert any("水泵频率" in a for a in out.alarms)

    cmd2 = ControlCommand(pump_freq_hz=80.0, mode="MID", n_chillers=1)
    out2 = sup.validate_command(cmd2, _benign_state())
    assert out2.pump_freq_hz == 50.0
    assert out2.overridden is True


def test_rule3_n_chillers_clamped_high() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(n_chillers=10, mode="HIGH")
    out = sup.validate_command(cmd, _benign_state())
    assert out.n_chillers == 3
    assert out.overridden is True
    assert any("启用机组台数" in a for a in out.alarms)


def test_rule3_n_chillers_clamped_low() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(n_chillers=-2, mode="MID")
    out = sup.validate_command(cmd, _benign_state())
    assert out.n_chillers == 0
    assert out.overridden is True


def test_rule4_vrf_demand_clamped() -> None:
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(vrf_demand_kw=9999.0, mode="LOW")
    out = sup.validate_command(cmd, _benign_state())
    assert out.vrf_demand_kw == 4000.0
    assert out.overridden is True
    assert any("VRF" in a for a in out.alarms)


def test_rule5_min_run_blocks_drop_to_low() -> None:
    sup = SafetySupervisor(_sys_config())
    state = _benign_state() | {"current_mode": "MID", "time_in_mode": 5.0}
    cmd = ControlCommand(mode="LOW", n_chillers=0)
    out = sup.validate_command(cmd, state)
    assert out.mode == "MID"
    assert out.overridden is True
    assert any("最小运行时间" in a for a in out.alarms)


def test_rule6_comm_timeout_forces_low() -> None:
    sup = SafetySupervisor(_sys_config())
    state = _benign_state() | {"comm_timeout": True}
    cmd = ControlCommand(mode="HIGH", n_chillers=3)
    out = sup.validate_command(cmd, state)
    assert out.mode == "LOW"
    assert out.n_chillers == 0
    assert out.overridden is True
    assert any("通讯中断" in a for a in out.alarms)


def test_rule7_ai_failure_uses_fallback_mode() -> None:
    sup = SafetySupervisor(_sys_config())
    state = _benign_state() | {"ai_failure": True, "fallback_mode": "MID"}
    cmd = ControlCommand(mode="HIGH", n_chillers=3)
    out = sup.validate_command(cmd, state)
    assert out.mode == "MID"
    assert out.overridden is True
    assert any("AI 策略失败" in a for a in out.alarms)


def test_rule8_indoor_temp_breach_forces_high_under_heavy_load() -> None:
    sup = SafetySupervisor(_sys_config())
    state = _benign_state() | {"t_in": 28.0, "target_load_kw": 8000.0, "th_high": 6000.0}
    cmd = ControlCommand(mode="LOW", n_chillers=0)
    out = sup.validate_command(cmd, state)
    assert out.mode == "HIGH"
    assert out.overridden is True
    assert any("室内温度安全超限" in a for a in out.alarms)


def test_rule8_indoor_temp_breach_forces_mid_under_moderate_load() -> None:
    sup = SafetySupervisor(_sys_config())
    state = _benign_state() | {"t_in": 28.0, "target_load_kw": 2500.0, "th_high": 6000.0}
    cmd = ControlCommand(mode="LOW", n_chillers=0)
    out = sup.validate_command(cmd, state)
    assert out.mode == "MID"
    assert out.overridden is True


# ---------------------------------------------------------------- combos

@pytest.mark.parametrize("attr,value,expected", [
    ("chw_supply_temp_c", 4.0, 5.0),
    ("pump_freq_hz", 100.0, 50.0),
    ("vrf_demand_kw", 50000.0, 4000.0),
])
def test_clamps_are_idempotent(attr: str, value: float, expected: float) -> None:
    """A second validation pass must not re-trigger a clamp alarm."""
    sup = SafetySupervisor(_sys_config())
    cmd = ControlCommand(**{attr: value}, mode="MID", n_chillers=1)
    out = sup.validate_command(cmd, _benign_state())
    assert getattr(out, attr) == expected
    out2 = sup.validate_command(out, _benign_state())
    assert getattr(out2, attr) == expected
    # The fresh copy carries the previous alarms; the second pass must not
    # add a duplicate. Counting the number of clamp alarms is sufficient.
    expected_marker = {
        "chw_supply_temp_c": "冷冻水供水温度",
        "pump_freq_hz": "水泵频率",
        "vrf_demand_kw": "VRF",
    }[attr]
    n_first = sum(1 for a in out.alarms if expected_marker in a)
    n_second = sum(1 for a in out2.alarms if expected_marker in a)
    assert n_first == 1
    assert n_second == 1
