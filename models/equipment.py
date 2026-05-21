"""Equipment model and registry for chiller / VRF / base units."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np


class EquipmentModel:
    """Wraps a 2-D ``RegularGridInterpolator(T_out, PLR)`` lookup.

    :meth:`calculate_cop` returns the **base** 2-D-interpolated COP. Callers
    that need cooling-water (CW) or chilled-water (CHW) temperature corrections
    must apply them on top of this base value (e.g.
    :class:`core.optimizer.chiller_group.ChillerGroupOptimizer` multiplies by
    ``(1 - K_CW * (T_cw - 32)) * (1 + K_CHW * (T_chw - 7))``).
    """

    def __init__(self, name: str, interpolator_ref: Any) -> None:
        self.name = name
        self.interpolator = interpolator_ref

    def calculate_cop(
        self,
        t_out: float,
        plr: float,
        sys_config: dict,
        log_callback: Callable[[str, str], None] | None = None,
        alarms_list: list | None = None,
    ) -> float:
        t_arr = sys_config["cop_tables"]["T_out"]
        p_arr = sys_config["cop_tables"]["PLR"]
        t_out_safe = float(np.clip(t_out, min(t_arr), max(t_arr)))
        plr_safe = float(np.clip(plr, min(p_arr), max(p_arr)))
        if (t_out != t_out_safe or plr != plr_safe) and alarms_list is not None:
            msg = f"COP插值边界裁剪[{self.name}]: T_out={t_out}->{t_out_safe}, PLR={plr:.2f}->{plr_safe:.2f}"
            if msg not in alarms_list:
                alarms_list.append(msg)
                if log_callback:
                    log_callback("边界裁剪", msg)
        cop = self.interpolator([t_out_safe, plr_safe])[0]
        return round(float(cop), 2) if not np.isnan(cop) else 2.0


class EquipmentRegistry:
    """In-memory registry mapping equipment ``type_name`` → :class:`EquipmentModel`."""

    def __init__(self) -> None:
        self._registry: dict[str, EquipmentModel] = {}

    def register(self, type_name: str, model_instance: EquipmentModel) -> None:
        self._registry[type_name] = model_instance

    def get(self, type_name: str) -> EquipmentModel | None:
        return self._registry.get(type_name)


__all__ = ["EquipmentModel", "EquipmentRegistry"]
