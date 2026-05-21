"""Unit tests for :class:`core.optimizer.chiller_group.ChillerGroupOptimizer`.

These tests exercise the optimizer in isolation. A stub equipment model with
a deterministic ``calculate_cop -> 5.0`` substitutes for the real
``RegularGridInterpolator``-backed model so the tests do not depend on the
COP table or scipy interpolation.
"""

from __future__ import annotations

import pytest

from core.optimizer.chiller_group import ChillerGroupOptimizer


class _StubCentralModel:
    """Minimal :class:`models.equipment.EquipmentModel` substitute.

    Returns a constant base COP so the optimizer's own CW/CHW corrections
    determine the final value. Calls are recorded for inspection if needed.
    """

    name = "stub-central"

    def __init__(self, base_cop: float = 5.0) -> None:
        self._cop = float(base_cop)
        self.calls: list[tuple[float, float]] = []

    def calculate_cop(self, t_out: float, plr: float, sys_config: dict) -> float:
        self.calls.append((float(t_out), float(plr)))
        return self._cop


def _make_optimizer(min_plr: float = 0.15) -> ChillerGroupOptimizer:
    sys_config = {"safety": {"central_min_plr": min_plr}}
    return ChillerGroupOptimizer(_StubCentralModel(), sys_config)


# Rated capacity of CH-1 / CH-2 = 800 RT * 3.5169 ≈ 2813.52 kW (legacy default).
_UNIT_CAP_BIG_KW = 800.0 * ChillerGroupOptimizer.RT_TO_KW


def test_optimize_two_unit_split_basic() -> None:
    """Two big units share 4000 kW of demand within bounds."""
    opt = _make_optimizer(min_plr=0.15)
    res = opt.optimize(q_total_kw=4000.0, t_out=33.0, n_active=2)

    assert res["loads"][2] == 0.0
    assert sum(res["loads"]) == pytest.approx(4000.0, abs=1.0)
    lower = 0.15 * _UNIT_CAP_BIG_KW
    upper = _UNIT_CAP_BIG_KW
    for i in (0, 1):
        assert lower - 1e-6 <= res["loads"][i] <= upper + 1e-6
    assert res["total_power_kw"] > 0.0
    assert res["system_cop"] > 0.0
    assert res["status"].startswith("寻优")
    assert res["tou_price_per_kwh"] == 1.0
    assert res["dt_hr"] == 1.0
    assert res["cost_yuan"] == pytest.approx(res["total_power_kw"], abs=0.01)


def test_optimize_zero_active_returns_zero_result() -> None:
    """``n_active = 0`` short-circuits to the zero result."""
    opt = _make_optimizer()
    res = opt.optimize(q_total_kw=5000.0, t_out=33.0, n_active=0)

    assert res["status"] == "机组未启用"
    assert res["loads"] == [0.0, 0.0, 0.0]
    assert res["powers"] == [0.0, 0.0, 0.0]
    assert res["total_power_kw"] == 0.0
    assert res["system_cop"] == 0.0
    assert res["cost_yuan"] == 0.0


def test_optimize_over_capacity_is_clipped_with_alarm() -> None:
    """Demand above total rated capacity is clipped down with an alarm."""
    opt = _make_optimizer()
    alarms: list = []
    huge_demand = 1.0e6  # absurdly large demand to force capacity clip
    res = opt.optimize(
        q_total_kw=huge_demand,
        t_out=33.0,
        n_active=3,
        alarms_list=alarms,
    )

    total_cap = sum(opt.unit_caps_kw)
    assert sum(res["loads"]) == pytest.approx(total_cap, abs=1.0)
    assert any("[寻优]" in a and "裁剪" in a for a in alarms)


def test_optimize_below_min_plr_is_clipped_up_with_alarm() -> None:
    """Demand below the active units' min PLR floor is clipped up to it."""
    opt = _make_optimizer(min_plr=0.15)
    alarms: list = []
    # min_load with n_active=2 = 2 * 0.15 * 2813.52 ≈ 844 kW;
    # 100 kW is well below that, so the optimizer must clip up.
    res = opt.optimize(
        q_total_kw=100.0,
        t_out=33.0,
        n_active=2,
        alarms_list=alarms,
    )

    min_load = 2 * 0.15 * _UNIT_CAP_BIG_KW
    assert sum(res["loads"]) == pytest.approx(min_load, abs=1.0)
    assert any("[寻优]" in a and "裁剪" in a for a in alarms)


def test_min_plr_override_takes_precedence() -> None:
    """``min_plr_override`` overrides the sys_config safety value."""
    opt = _make_optimizer(min_plr=0.15)
    res = opt.optimize(
        q_total_kw=100.0,
        t_out=33.0,
        n_active=2,
        min_plr_override=0.30,
    )
    # New floor: 2 * 0.30 * cap ≈ 1688 kW, much larger than 100.
    expected_floor = 2 * 0.30 * _UNIT_CAP_BIG_KW
    assert sum(res["loads"]) == pytest.approx(expected_floor, abs=1.0)


def test_tou_price_records_cost_without_changing_allocation() -> None:
    """A positive TOU scalar records cost but leaves the optimum unchanged."""
    opt_a = _make_optimizer()
    opt_b = _make_optimizer()
    res_a = opt_a.optimize(q_total_kw=4000.0, t_out=33.0, n_active=2,
                           tou_price_per_kwh=1.0, dt_hr=1.0)
    res_b = opt_b.optimize(q_total_kw=4000.0, t_out=33.0, n_active=2,
                           tou_price_per_kwh=1.20, dt_hr=0.25)

    for i in range(3):
        assert res_a["loads"][i] == pytest.approx(res_b["loads"][i], abs=0.5)
    assert res_b["tou_price_per_kwh"] == 1.20
    assert res_b["dt_hr"] == 0.25
    assert res_b["cost_yuan"] == pytest.approx(
        res_b["total_power_kw"] * 0.25 * 1.20, abs=0.01
    )
