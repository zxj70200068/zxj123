"""Front-end control service for real-time DDC / BACnet gateways.

This is the **single** API a real edge gateway calls each loop:

    cmd = ControlService(sys_config, strategy_name='rule').compute_command(obs)

The service hides the five-layer chain (Prediction -> Optimization -> Rule
-> Safety -> Execution) behind a single :meth:`compute_command` call.
When ``low_sensor=True``, the supplied observation is first lifted by
:class:`core.control.low_sensor_mode.LowSensorMode` so degraded BAS
deployments still produce a coherent :class:`ControlCommand`.

The service never imports Tkinter and never returns engine internals; the
caller only sees a :class:`ControlCommand` instance (with primitive
fields and an ``alarms`` list of strings).
"""

from __future__ import annotations

from typing import Any

from core.control.control_chain import ControlChain
from core.control.low_sensor_mode import LowSensorMode
from core.control.strategies import (
    BaseStrategy,
    MPCStrategy,
    RuleBasedStrategy,
)
from core.safety.supervisor import ControlCommand, SafetySupervisor
from models.load_predictor import LoadPredictor
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
        "ControlService: unknown strategy_name=%r; falling back to 'rule'", name,
    )
    return RuleBasedStrategy()


class ControlService:
    """Compose strategy + safety supervisor + predictor into one call.

    Parameters
    ----------
    sys_config : dict
        Full system configuration (consumed by the supervisor).
    strategy_name : str, default 'rule'
        Either ``'rule'`` or ``'mpc'``. Unknown names degrade to ``'rule'``.
    low_sensor : bool, default False
        When True, every :meth:`compute_command` call first lifts the
        observation through :class:`LowSensorMode` so the chain still gets
        a fully populated state dict even if the BAS sensor list is thin.
    model_path : str or Path, optional
        Path to a persisted :class:`LoadPredictor` artefact. When None,
        no predictor is wired into the chain (the prediction layer is a
        no-op in that case).
    """

    def __init__(
        self,
        sys_config: dict[str, Any],
        strategy_name: str = "rule",
        low_sensor: bool = False,
        model_path: str | None = None,
    ) -> None:
        self.sys_config = sys_config
        self.strategy: BaseStrategy = _build_strategy(strategy_name)
        self.supervisor: SafetySupervisor = SafetySupervisor(sys_config)
        self.chain: ControlChain = ControlChain()
        self.low_sensor: bool = bool(low_sensor)
        self._lifter: LowSensorMode | None = (
            LowSensorMode(sys_config) if self.low_sensor else None
        )
        self.predictor: LoadPredictor | None = None
        if model_path:
            try:
                self.predictor = LoadPredictor(model_path)
            except Exception:
                _logger.exception(
                    "ControlService: failed to instantiate LoadPredictor at %r",
                    model_path,
                )
                self.predictor = None

    # --------------------------------------------------------- main entry
    def compute_command(self, observation: dict[str, Any]) -> ControlCommand:
        """Run prediction -> optimization -> rule -> safety; return the command.

        Parameters
        ----------
        observation : dict
            Either a thin sensor snapshot (when ``low_sensor=True``) or a
            full ``engine_state`` dict suitable for
            :meth:`ControlChain.step`. Missing keys are tolerated by the
            chain's safety layer (it falls back to documented defaults).
        """
        obs = observation if isinstance(observation, dict) else {}
        if self.low_sensor and self._lifter is not None:
            engine_state = self._lifter.lift(obs)
            # Preserve any extra keys the caller already passed in (eg. a
            # forced ``current_mode``); the lift's defaults are filled in
            # only where the caller did not provide a value.
            for k, v in obs.items():
                engine_state.setdefault(k, v)
        else:
            engine_state = dict(obs)

        return self.chain.step(
            engine_state=engine_state,
            sys_config=self.sys_config,
            strategy=self.strategy,
            supervisor=self.supervisor,
            predictor=self.predictor,
        )


__all__ = ["ControlService"]
