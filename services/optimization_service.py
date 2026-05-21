"""Chiller-group optimization service (thin pass-through).

The wrapper exists so that future swap-ins (MILP via Pyomo, SCIP, mixed
SLSQP+heuristic warm starts, ...) can be performed without touching UI /
service consumers. Today it is a one-line delegate to
:class:`core.optimizer.chiller_group.ChillerGroupOptimizer`.
"""

from __future__ import annotations

from typing import Any

from core.optimizer.chiller_group import ChillerGroupOptimizer


class OptimizationService:
    """Holds a configured :class:`ChillerGroupOptimizer` instance.

    Parameters
    ----------
    sys_config : dict
        Global system configuration (must contain ``safety.central_min_plr``).
    central_model : EquipmentModel-like
        Provides ``calculate_cop(t_out, plr, sys_config) -> float``.
    """

    def __init__(self, sys_config: dict[str, Any], central_model: Any) -> None:
        self.sys_config = sys_config
        self._optimizer = ChillerGroupOptimizer(
            central_model=central_model, sys_config=sys_config,
        )

    def optimize(
        self,
        q_total_kw: float,
        t_out: float,
        n_active: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Allocate cooling load across active chillers (pass-through).

        See :meth:`ChillerGroupOptimizer.optimize` for the full keyword
        list. The future MILP swap-in will accept the same signature so
        callers never need to change.
        """
        return self._optimizer.optimize(
            q_total_kw=q_total_kw,
            t_out=t_out,
            n_active=int(n_active),
            **kwargs,
        )


__all__ = ["OptimizationService"]
