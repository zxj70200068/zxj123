"""Behavioural smoke tests for the new services/ layer (FEAT-004).

Three contracts are pinned here:

1. :class:`services.simulation_service.SimulationService` ``run_single_step``
   returns a dict shaped like the legacy engine result (``opt_p``, ``t_in``,
   ``cmd`` with an ``alarms`` list).
2. :class:`services.control_service.ControlService` instantiated in
   degraded "low sensor mode" returns a :class:`ControlCommand` with the
   ``overridden`` boolean and ``alarms`` list populated.
3. :class:`services.reporting_service.ReportingService` ``summarize_run``
   returns at least 100 chars of text even when the history CSV is
   missing (deterministic boilerplate path).
"""

from __future__ import annotations

import json
from pathlib import Path

from core.config import ConfigManager
from core.safety.supervisor import ControlCommand
from data.configs.defaults import DEFAULT_SYS_CONFIG
from services.control_service import ControlService
from services.reporting_service import ReportingService
from services.simulation_service import SimulationService


def test_simulation_service_run_single_step_returns_full_result_dict() -> None:
    cm = ConfigManager()
    svc = SimulationService(cm)
    bk = next(iter(cm.building_configs))
    factor = next(iter(cm.scenarios.values()))

    res = svc.run_single_step(bk, factor, strategy_name="rule", dt_min=15)

    assert isinstance(res, dict)
    for key in ("opt_p", "t_in", "cmd"):
        assert key in res, f"missing key {key!r} in result dict"
    assert isinstance(res["cmd"], dict)
    assert isinstance(res["cmd"].get("alarms"), list)
    assert isinstance(res["opt_p"], (int, float))
    assert isinstance(res["t_in"], (int, float))


def test_simulation_service_from_defaults_factory() -> None:
    """The UI-friendly factory wires up a usable service with no args."""
    svc = SimulationService.from_defaults()
    assert isinstance(svc, SimulationService)
    assert svc.config_manager is not None
    bk = next(iter(svc.config_manager.building_configs))
    factor = next(iter(svc.config_manager.scenarios.values()))
    res = svc.run_single_step(bk, factor)
    assert "opt_p" in res


def test_control_service_low_sensor_returns_control_command() -> None:
    sys_config = json.loads(DEFAULT_SYS_CONFIG)
    cs = ControlService(sys_config, strategy_name="rule", low_sensor=True)
    obs = {
        "chiller_power_kw": 200.0,
        "t_out": 32.0,
        "hour": 14.0,
        "chw_supply_c": 7.0,
        "chw_return_c": 12.0,
        "zone_temps": {"hall": 24.5, "office": 25.1},
    }
    cmd = cs.compute_command(obs)
    assert isinstance(cmd, ControlCommand)
    assert cmd.mode in ("LOW", "MID", "HIGH")
    assert isinstance(cmd.overridden, bool)
    assert isinstance(cmd.alarms, list)


def test_reporting_service_summarize_run_on_empty_history() -> None:
    # Point at a path that doesn't exist; the service must not raise and
    # must still produce >= 100 chars of boilerplate text.
    svc = ReportingService(history_path=Path("/tmp/__no_such_history.csv"))
    out = svc.summarize_run("test")
    assert isinstance(out, str)
    assert len(out) >= 100, f"summary too short ({len(out)} chars): {out!r}"


def test_reporting_service_explain_alarm_no_llm_returns_boilerplate() -> None:
    svc = ReportingService()
    text = svc.explain_alarm("水力测点告警[公共大厅]: 流速过高")
    assert isinstance(text, str)
    assert len(text) >= 50
    assert "告警" in text or "alarm" in text.lower()
