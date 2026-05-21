"""Lumped-capacity thermal models for room and process buffers."""

from __future__ import annotations


class RoomRCModel:
    """First-order RC building thermal model.

    State variable :attr:`t_in` (indoor air temperature, ℃) advances each step
    by the difference between heat gain (load minus delivered cooling) and
    envelope conduction toward the outdoor temperature.
    """

    def __init__(self, config: dict) -> None:
        self.t_in: float = 24.0
        self.params: dict = config["rc_model_params"]

    def step(
        self,
        t_out: float,
        q_load_kw: float,
        q_cooling_delivered_kw: float,
        dt_min: float,
    ) -> float:
        dt_hr = dt_min / 60.0
        self.t_in += (
            (q_load_kw - q_cooling_delivered_kw) * self.params["heat_gain_coeff"] * dt_hr
            + (t_out - self.t_in) * self.params["envelope_ua_coeff"] * dt_hr
        )
        return round(self.t_in, 2)


class ThermalBuffer:
    """First-order low-pass filter for a slowly-varying load signal.

    Tracks the previous load and applies an exponential smoothing toward the
    target with time constant ``tau_min``.
    """

    def __init__(self) -> None:
        self.prev_load: float | None = None

    def step(
        self,
        target_load: float,
        dt_min: float,
        tau_min: float,
        reset: bool = False,
    ) -> float:
        if reset or self.prev_load is None:
            self.prev_load = target_load
            return target_load
        alpha = dt_min / (tau_min + dt_min) if (tau_min + dt_min) > 0 else 1.0
        self.prev_load = self.prev_load + alpha * (target_load - self.prev_load)
        return round(self.prev_load, 2)


__all__ = ["RoomRCModel", "ThermalBuffer"]
