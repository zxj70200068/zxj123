"""Five-layer industrial control chain.

The chain orchestrates the supervisory decision per simulation step and is
the **single** entry point used by the simulation engine and the future
``services/control_service.py``. Layers in the order they are *labelled*:

1. Prediction   -- run the local load forecaster and attach the result to
                   ``engine_state['predicted_next_load_kw']``.
2. Optimization -- when the proposed mode is ``MID`` or ``HIGH``, compute
                   the desired chiller-unit count via
                   :class:`core.optimizer.chiller_group.ChillerGroupOptimizer`.
                   Bypassed entirely for ``LOW`` (VRF only).
3. Rule         -- delegate to the supplied :class:`BaseStrategy`. When
                   ``engine_state['_engine']`` is present the strategy is
                   called directly; otherwise a simple threshold fallback
                   based on ``target_load_kw`` is used so the chain can be
                   exercised in unit tests without the heavy WhiteBoxEngine.
4. Safety       -- delegate to :meth:`SafetySupervisor.validate_command`.
                   This stage is the **only** one that may add alarms or
                   set ``overridden=True``.
5. Execution    -- return the final :class:`ControlCommand`.

Note on layer ordering: the *labels* place Optimization before Rule, but in
real time the rule layer must produce the proposed mode before the
optimizer knows whether to run; the chain therefore evaluates the rule
first and folds optimisation into the build of the initial command. This
matches the legacy ``WhiteBoxEngine.execute_step`` flow byte-for-byte.
"""

from __future__ import annotations

from typing import Any

from core.optimizer.chiller_group import ChillerGroupOptimizer
from core.safety.supervisor import ControlCommand, SafetySupervisor
from prediction.load_forecast_service import predict_next_load
from utils.logging import get_logger

from .strategies import BaseStrategy

_logger = get_logger(__name__)


class ControlChain:
    """Stateless orchestrator for the five-layer control step."""

    def step(
        self,
        engine_state: dict[str, Any],
        sys_config: dict[str, Any],
        strategy: BaseStrategy,
        supervisor: SafetySupervisor,
        predictor: Any | None,
    ) -> ControlCommand:
        """Run the five layers and return the final :class:`ControlCommand`.

        Parameters
        ----------
        engine_state : dict
            Mutable runtime state. Recognised optional keys:

            * ``_engine``, ``_factor``, ``_dt`` -- when present, the rule
              layer delegates to ``strategy.decide_mode(engine, factor, dt)``.
            * ``target_load_kw`` -- used by the rule fallback and the
              prediction layer.
            * ``time_in_mode``, ``current_mode``, ``t_in``, ``comm_timeout``,
              ``ai_failure``, ``fallback_mode`` -- consumed by the safety
              supervisor.
        sys_config : dict
            Full system configuration. Same shape consumed by the
            supervisor and optimizer.
        strategy : BaseStrategy
            Local control strategy. Currently :class:`RuleBasedStrategy` or
            :class:`MPCStrategy`.
        supervisor : SafetySupervisor
            Final clamp + override stage.
        predictor : LoadPredictor or None
            Optional load forecaster. When provided, its model path is
            forwarded to :func:`prediction.load_forecast_service.predict_next_load`.
        """
        # ---- Prediction layer --------------------------------------------
        if predictor is not None:
            try:
                model_path = getattr(predictor, "model_path", None)
                predicted = predict_next_load(
                    engine_state, model_path=model_path,
                )
                engine_state["predicted_next_load_kw"] = float(predicted)
            except Exception:
                _logger.exception("ControlChain.prediction layer failed")
                engine_state.setdefault(
                    "predicted_next_load_kw",
                    float(engine_state.get("target_load_kw", 0.0)),
                )

        # ---- Rule layer --------------------------------------------------
        proposed_mode = self._rule_layer(engine_state, sys_config, strategy)

        # ---- Optimization layer ------------------------------------------
        n_chillers = 0
        if proposed_mode in ("MID", "HIGH"):
            n_chillers = self._optimize_n_chillers(
                engine_state=engine_state,
                sys_config=sys_config,
                proposed_mode=proposed_mode,
            )

        # ---- Build initial command ---------------------------------------
        cmd = ControlCommand(
            mode=proposed_mode,
            n_chillers=int(n_chillers),
            vrf_demand_kw=float(engine_state.get("vrf_demand_kw", 0.0)),
            chw_supply_temp_c=float(engine_state.get("chw_supply_temp_c", 7.0)),
            pump_freq_hz=float(engine_state.get("pump_freq_hz", 30.0)),
            alarms=[],
            overridden=False,
        )

        # ---- Safety layer ------------------------------------------------
        cmd = supervisor.validate_command(cmd, engine_state)

        # ---- Execution layer ---------------------------------------------
        return cmd

    # ------------------------------------------------------------------ rule
    @staticmethod
    def _rule_layer(
        engine_state: dict[str, Any],
        sys_config: dict[str, Any],
        strategy: BaseStrategy,
    ) -> str:
        """Choose the proposed mode via strategy or built-in threshold."""
        engine = engine_state.get("_engine")
        factor = engine_state.get("_factor")
        dt = engine_state.get("_dt")
        if engine is not None and factor is not None and dt is not None:
            try:
                proposed = strategy.decide_mode(engine, factor, dt)
                return proposed if proposed in ("LOW", "MID", "HIGH") else "LOW"
            except Exception:
                _logger.exception("ControlChain.rule layer strategy failed")
                # Fall through to the threshold fallback below.

        # Built-in threshold fallback (mirrors RuleBasedStrategy without
        # requiring zone-level state).
        target_load = float(engine_state.get("target_load_kw", 0.0))
        is_night = bool(engine_state.get("is_night", False))
        if is_night:
            return "LOW"
        th_high = float(engine_state.get("th_high", 6000.0))
        th_mid = float(engine_state.get("th_mid", 2200.0))
        if target_load > th_high:
            return "HIGH"
        if target_load > th_mid:
            return "MID"
        return "LOW"

    # ------------------------------------------------------------ optimization
    @staticmethod
    def _optimize_n_chillers(
        engine_state: dict[str, Any],
        sys_config: dict[str, Any],
        proposed_mode: str,
    ) -> int:
        """Compute the desired chiller-unit count for ``proposed_mode``.

        Prefers a precomputed ``engine_state['desired_chillers']`` (set by
        WhiteBoxEngine before invoking the chain) and otherwise falls back
        to a simple cumulative-capacity walk that mirrors the legacy
        big-machine-first staging policy.
        """
        if "desired_chillers" in engine_state:
            return int(engine_state["desired_chillers"])
        equipment = sys_config.get("equipment", {})
        chiller_total = int(equipment.get("chiller_total_units", 0))
        cap_total = float(equipment.get("capacity_central_kw", 0.0))
        if chiller_total <= 0 or cap_total <= 0:
            return 0
        unit_caps = ChillerGroupOptimizer.DEFAULT_UNIT_RT
        unit_caps_kw = [u * ChillerGroupOptimizer.RT_TO_KW for u in unit_caps]
        # When the proposed mode is HIGH, demand the full target load; for
        # MID, demand the public-CHW share which we approximate as 70 %.
        share = 1.0 if proposed_mode == "HIGH" else 0.7
        q_required = float(engine_state.get("target_load_kw", 0.0)) * share
        desired = 0
        for k in range(min(chiller_total, len(unit_caps_kw))):
            desired = k + 1
            if sum(unit_caps_kw[: k + 1]) >= q_required:
                break
        return min(desired, chiller_total)


__all__ = ["ControlChain"]
