"""Engine-level integration tests for the v1 review safety-critical fixes.

These tests exercise :class:`core.simulation.engine.WhiteBoxEngine` end-to-end
through :class:`SimulationService`, asserting the three behaviours pinned
by the v1 review response:

* Concern #2 -- a supervisor-forced drop to LOW (rule 6 ``comm_timeout``)
  bypasses the engine's anti-chatter ``min_stop_minutes`` lockout. The
  engine must transition to LOW on the same step the override fires,
  not delay it.
* Concern #3 -- when ``control_chain.step`` raises, the engine routes the
  fallback through :meth:`SafetySupervisor.validate_command` so rule 8's
  indoor-temp escalation can still fire on the failure path.
* Concern #11 -- the engine's result dict surfaces ``proposed_mode``
  (the rule layer's pre-safety proposal) alongside the post-safety
  ``ai_requested_mode``, so the report can compute ``is_revised``.
"""

from __future__ import annotations

from typing import Any

from core.config import ConfigManager
from core.safety.supervisor import ControlCommand
from services.simulation_service import SimulationService


def _service() -> tuple[SimulationService, str, dict]:
    cm = ConfigManager()
    svc = SimulationService(cm)
    bk = next(iter(cm.building_configs))
    factor = next(iter(cm.scenarios.values()))
    return svc, bk, dict(factor)


def test_comm_timeout_drops_to_low_on_same_step_bypassing_anti_chatter() -> None:
    """Concern #2: rule 6 LOW override must bypass the engine's lockout."""
    svc, bk, factor = _service()
    engine = svc._get_engine(bk)
    # Force the engine into MID with a fresh ``time_in_mode`` of 0 so
    # the legacy code path would have held MID until ``min_run_minutes``.
    engine.current_mode = "MID"
    engine.time_in_mode = 0.0
    engine.current_chillers = 1

    factor_to = dict(factor)
    factor_to["comm_timeout"] = True
    res = svc.run_single_step(bk, factor_to, strategy_name="rule", dt_min=15)

    assert engine.current_mode == "LOW"
    assert res["combo"] == "LOW"
    assert res["safety_override"] is True
    # The supervisor's rule 6 alarm must be present on the cmd.
    assert any(
        "通讯中断" in a for a in res["cmd"]["alarms"]
    ), f"missing comm_timeout alarm: {res['cmd']['alarms']!r}"


def test_chain_exception_still_triggers_supervisor_indoor_temp_escalation(
    monkeypatch: Any,
) -> None:
    """Concern #3: even if ControlChain.step raises, rule 8 must still fire."""
    svc, bk, factor = _service()
    engine = svc._get_engine(bk)
    # Force a hot indoor temperature so rule 8 must escalate the mode.
    engine.rc_model.t_in = 28.5

    def boom(*args: Any, **kwargs: Any) -> ControlCommand:
        raise RuntimeError("synthetic chain failure")

    monkeypatch.setattr(engine.control_chain, "step", boom)

    res = svc.run_single_step(bk, factor, strategy_name="rule", dt_min=15)

    # The supervisor escalates to at least MID (HIGH if load is heavy).
    assert res["combo"] in ("MID", "HIGH"), (
        f"expected MID/HIGH after failure-path supervisor escalation, "
        f"got {res['combo']!r}"
    )
    assert res["safety_override"] is True
    # The rule 8 alarm must be present.
    assert any(
        "室内温度安全超限" in a for a in res["cmd"]["alarms"]
    ), f"missing indoor-temp breach alarm: {res['cmd']['alarms']!r}"


def test_engine_result_dict_exposes_proposed_mode_alongside_ai_requested_mode() -> None:
    """Concern #11: ``proposed_mode`` (pre-safety) is surfaced separately."""
    svc, bk, factor = _service()
    res = svc.run_single_step(bk, factor, strategy_name="rule", dt_min=15)
    assert "proposed_mode" in res
    assert "ai_requested_mode" in res
    assert res["proposed_mode"] in ("LOW", "MID", "HIGH")


def test_predicted_next_load_kw_surfaces_when_predictor_is_wired(
    monkeypatch: Any,
) -> None:
    """Concern #1: the prediction layer's output is observable.

    Even if no downstream stage consumes ``predicted_next_load_kw`` for
    a control decision today, the engine state dict must carry the
    forecast so reporting / observability can see it. This test pins
    the "instrumentation hook" contract called out in REFACTOR_NOTES.
    """
    svc, bk, factor = _service()
    engine = svc._get_engine(bk)

    captured: dict[str, Any] = {}
    original_step = engine.control_chain.step

    def spy_step(**kwargs: Any) -> ControlCommand:
        captured["engine_state"] = kwargs.get("engine_state")
        return original_step(**kwargs)

    monkeypatch.setattr(engine.control_chain, "step", spy_step)

    class _StubPredictor:
        model_path = "models/saved/load_forecast_lr.joblib"

    engine.predictor = _StubPredictor()
    svc.run_single_step(bk, factor, strategy_name="rule", dt_min=15)

    state = captured["engine_state"]
    # The predictor populates this key during the prediction layer; the
    # safety + execution layers may add more keys but must not delete it.
    assert "predicted_next_load_kw" in state
    assert state["predicted_next_load_kw"] >= 0.0
