"""Life-cycle cost estimator (TOU-aware)."""

from __future__ import annotations

from typing import Any


class LCCEstimator:
    """Time-of-use aware kWh / cost / NPV estimator.

    Accepts the full ``sys_config`` dict and reads its ``economics`` subsection.
    The class is otherwise stateless except for accumulating saved kWh/yuan
    across ``add_kwh`` calls.
    """

    def __init__(self, sys_config: dict) -> None:
        self.cfg: dict = sys_config["economics"]
        self.total_kwh_saved: float = 0.0
        self.total_cost_saved: float = 0.0

    def get_price_by_hour(self, hour: int) -> float:
        tou = self.cfg.get("tou_price", {})
        if tou.get("use_tou", False):
            if hour in tou.get("peak_hours", []):
                return tou.get("peak_price", 1.20)
            elif hour in tou.get("valley_hours", []):
                return tou.get("valley_price", 0.35)
            else:
                return tou.get("flat_price", 0.80)
        return self.cfg.get("elec_price_flat", 0.8)

    def add_kwh(self, saved_kw: float, dt_min: float, current_time_min: float) -> None:
        saved_kwh = saved_kw * (dt_min / 60.0)
        self.total_kwh_saved += saved_kwh
        self.total_cost_saved += saved_kwh * self.get_price_by_hour(int((current_time_min / 60) % 24))

    def evaluate_annual(self) -> dict[str, Any] | None:
        if self.total_kwh_saved <= 0:
            return None
        season_saved_yuan = (
            self.total_cost_saved
            * self.cfg.get("cooling_season_days", 150)
            * self.cfg.get("seasonal_load_coeff", 0.65)
        )
        annual_saved_万元 = season_saved_yuan / 10000.0
        capex = self.cfg["capex_diff_万元"]
        net_cf = annual_saved_万元 - self.cfg["maint_diff_万元"]
        if net_cf <= 0:
            return {
                "NPV": -capex,
                "Payback": 999.0,
                "Annual_Saving": round(annual_saved_万元, 2),
                "use_tou": self.cfg.get("tou_price", {}).get("use_tou", False),
            }
        npv = -capex
        discount_rate = self.cfg.get("discount_rate", 0.05)
        for t in range(1, self.cfg["life_years"] + 1):
            npv += net_cf / ((1 + discount_rate) ** t)
        return {
            "NPV": round(npv, 2),
            "Payback": round(capex / net_cf, 1),
            "Annual_Saving": round(annual_saved_万元, 2),
            "use_tou": self.cfg.get("tou_price", {}).get("use_tou", False),
        }


__all__ = ["LCCEstimator"]
