"""Three-unit magnetic-bearing chiller group load allocator.

Control objective
-----------------
Minimize the total electrical power consumed by the chiller group at the
current step:

    minimize    sum_i  Q_i / COP_i(T_out, PLR_i, T_cw, T_chw)
    subject to  sum_i  Q_i  = Q_total                (cooling balance)
                Q_i_min  <=  Q_i  <=  Q_i_rated      (capacity bounds)

A scalar TOU electricity price is recorded with the result so callers can
compare per-step cost across timesteps; the price does NOT enter the
objective (multiplying by a positive constant leaves the argmin unchanged),
so the optimal load split is identical with or without TOU.

Operational protections
-----------------------
* **Anti-surge minimum PLR** — every running unit is bounded below by
  ``min_plr_override`` (or ``sys_config['safety']['central_min_plr']``) times
  its rated capacity to keep magnetic-bearing chillers out of their
  surge region.
* **Capacity bounds** — demand is clipped into ``[sum(min_load), sum(cap)]``
  and an alarm is appended when clipping occurs.
* **SLSQP + retry-with-uniform fallback** — the SLSQP non-linear solver is
  the primary path; if it fails (or raises) the allocator falls back to the
  capacity-weighted uniform initial guess. Failures are logged through
  :func:`utils.logging.get_logger`.
* **Per-step semantics** — the optimizer is per-step. Time integration of
  power/cost is the responsibility of the service layer; ``dt_hr`` is
  passed only so the per-step ``cost_yuan`` can be computed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import Bounds as SpBounds
from scipy.optimize import minimize

from utils.logging import get_logger

_logger = get_logger(__name__)


class ChillerGroupOptimizer:
    """Three-unit magnetic-bearing chiller load optimizer.

    The legacy default plant has CH-1=800 RT, CH-2=800 RT, CH-3=430 RT
    (≈ 7139.3 kW total, matching ``capacity_central_kw=7140``). All three
    plant-specific parameters (``UNIT_RT``, ``UNIT_NAMES``, ``K_CW``,
    ``K_CHW``) are constructor-overridable so other plants can reuse the
    same allocator.
    """

    # ── Physical constants ─────────────────────────────────────────────
    RT_TO_KW: float = 3.5169           # 1 RT in kW
    CW_DESIGN_TEMP: float = 32.0       # 冷却水供水设计温度 (℃)
    CHW_DESIGN_TEMP: float = 7.0       # 冷冻水供水设计温度 (℃)

    # Defaults preserved from the legacy implementation.
    DEFAULT_UNIT_RT: tuple[float, ...] = (800.0, 800.0, 430.0)
    DEFAULT_UNIT_NAMES: tuple[str, ...] = ("CH-1(800RT)", "CH-2(800RT)", "CH-3(430RT)")
    DEFAULT_K_CW: float = 0.020        # 冷凝侧修正系数 (每 ℃)
    DEFAULT_K_CHW: float = 0.015       # 蒸发侧修正系数 (每 ℃)

    def __init__(
        self,
        central_model: Any,
        sys_config: dict,
        unit_rt: list[float] | None = None,
        unit_names: list[str] | None = None,
        k_cw: float | None = None,
        k_chw: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        central_model : EquipmentModel-like
            Provides ``calculate_cop(t_out, plr, sys_config) -> float`` for
            the chiller's base 2-D-interpolated COP. CW/CHW corrections are
            applied here (the model returns the un-corrected value).
        sys_config : dict
            Global system config dict; must contain ``safety.central_min_plr``.
        unit_rt, unit_names : list, optional
            Per-unit rated cooling tons and display names. Defaults preserve
            the legacy 3-unit [800, 800, 430] / CH-N(NNN RT) layout.
        k_cw, k_chw : float, optional
            COP correction slopes per ℃ on the condenser and evaporator
            sides. Defaults preserve the legacy 0.020 / 0.015 values.
        """
        self.model = central_model
        self.sys_config = sys_config

        self.UNIT_RT: list[float] = list(unit_rt) if unit_rt is not None else list(self.DEFAULT_UNIT_RT)
        self.UNIT_NAMES: list[str] = (
            list(unit_names) if unit_names is not None else list(self.DEFAULT_UNIT_NAMES)
        )
        self.K_CW: float = float(k_cw) if k_cw is not None else self.DEFAULT_K_CW
        self.K_CHW: float = float(k_chw) if k_chw is not None else self.DEFAULT_K_CHW

        # 各机额定冷量 (kW)，与配置 capacity_central_kw=7140 kW 吻合
        self.unit_caps_kw: list[float] = [rt * self.RT_TO_KW for rt in self.UNIT_RT]
        self._last_result: dict = {}

    # ── 内部：修正版 COP 查询（等效三维插值） ────────────────────────
    def _query_cop(
        self,
        t_out: float,
        plr: float,
        t_cw: float = 32.0,
        t_chw: float = 7.0,
    ) -> float:
        """
        通过现有 RegularGridInterpolator(T_out, PLR) 查询基准 COP，
        叠加冷却水 / 冷冻水温度物理修正，实现等效三维 COP 响应面。

        修正公式（磁悬浮机组工程拟合）：
          COP_3D = COP_base(T_out, PLR)
                   × [1 - K_cw × (T_cw - T_cw_design)]    ← 冷凝侧修正
                   × [1 + K_chw × (T_chw - T_chw_design)] ← 蒸发侧修正
        """
        cop_base = self.model.calculate_cop(t_out, plr, self.sys_config)

        cw_corr = 1.0 - self.K_CW * (t_cw - self.CW_DESIGN_TEMP)
        cw_corr = float(np.clip(cw_corr, 0.50, 1.20))

        chw_corr = 1.0 + self.K_CHW * (t_chw - self.CHW_DESIGN_TEMP)
        chw_corr = float(np.clip(chw_corr, 0.75, 1.25))

        cop_3d = cop_base * cw_corr * chw_corr
        return max(1.0, round(cop_3d, 4))

    # ── 核心：负荷寻优分配 ────────────────────────────────────────────
    def optimize(
        self,
        q_total_kw: float,
        t_out: float,
        n_active: int,
        t_cw: float = 32.0,
        t_chw: float = 7.0,
        alarms_list: list | None = None,
        tou_price_per_kwh: float = 1.0,
        dt_hr: float = 1.0,
        min_plr_override: float | None = None,
    ) -> dict[str, Any]:
        """Allocate cooling load across the running chiller units.

        Parameters
        ----------
        q_total_kw : float
            Total cooling demand for this step (kW).
        t_out : float
            Outdoor dry-bulb temperature (℃) used as the COP base lookup axis.
        n_active : int
            Number of units to run, 0..len(unit_rt). Big-machine-first
            staging policy: indices 0..n_active-1 are active.
        t_cw, t_chw : float
            Condenser and evaporator water supply temperatures (℃) for
            the COP correction.
        alarms_list : list, optional
            Mutable list to append alarm strings to (capacity clip,
            anti-surge clip, SLSQP non-convergence).
        tou_price_per_kwh : float, default 1.0
            Time-of-use electricity price scalar. Recorded on the result as
            ``tou_price_per_kwh``; ``cost_yuan = total_power_kw * dt_hr *
            tou_price_per_kwh``. Does NOT scale the objective so the optimal
            allocation is independent of this value.
        dt_hr : float, default 1.0
            Step length in hours. Used only to compute the per-step
            ``cost_yuan`` field; the optimizer itself is per-step.
        min_plr_override : float, optional
            If provided, takes precedence over
            ``sys_config['safety']['central_min_plr']`` for the anti-surge
            minimum PLR.

        Returns
        -------
        dict
            ``loads``, ``powers``, ``cops``, ``plrs`` (per-unit, length =
            len(unit_rt)); ``total_power_kw``, ``system_cop``, ``status``;
            ``tou_price_per_kwh``, ``dt_hr``, ``cost_yuan``.
        """
        if n_active <= 0 or q_total_kw <= 0:
            return self._zero_result(
                tou_price_per_kwh=tou_price_per_kwh,
                dt_hr=dt_hr,
            )

        caps = self.unit_caps_kw
        n_total = len(caps)
        n_active = min(int(n_active), n_total)

        if min_plr_override is not None:
            c_min = float(min_plr_override)
        else:
            c_min = float(self.sys_config["safety"]["central_min_plr"])

        # ── 投机策略：大机优先（CH-1, CH-2 先投；CH-3 最后）──────────
        active_idx = list(range(n_active))
        cap_active = [caps[i] for i in active_idx]

        # ── 可行域 ─────────────────────────────────────────────────────
        max_cap = sum(cap_active)
        min_load = sum(caps[i] * c_min for i in active_idx)

        q_req = float(np.clip(q_total_kw, min_load, max_cap))
        if abs(q_req - q_total_kw) > 1.0 and alarms_list is not None:
            alarms_list.append(
                f"[寻优] 需求冷量 {q_total_kw:.0f} kW 超出"
                f" [{min_load:.0f}, {max_cap:.0f}] kW 区间，已裁剪至 {q_req:.0f} kW"
            )

        # ── 决策变量 x[j] = 第 j 台运行机组的冷量分配 (kW) ───────────
        cap_sum = sum(cap_active)
        x0 = np.array([q_req * c / cap_sum for c in cap_active])

        lb = [caps[i] * c_min for i in active_idx]
        ub = [caps[i] for i in active_idx]
        bounds = SpBounds(lb, ub, keep_feasible=True)

        # ── 目标函数：最小化合计电功耗 Σ Q_i / COP_i ─────────────────
        def objective(x: np.ndarray) -> float:
            total_p = 0.0
            for j, i in enumerate(active_idx):
                plr_j = float(np.clip(x[j] / caps[i], c_min, 1.2))
                cop_j = self._query_cop(t_out, plr_j, t_cw, t_chw)
                total_p += x[j] / max(cop_j, 0.1)
            return total_p

        constraints = [{"type": "eq", "fun": lambda x: float(np.sum(x)) - q_req}]

        # ── 调用 SLSQP 非线性规划求解器 ───────────────────────────────
        opt_status = "寻优成功(SLSQP)"
        try:
            res = minimize(
                objective, x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-8, "maxiter": 500, "disp": False, "eps": 1e-6},
            )
            if res.success:
                x_opt = res.x
                opt_status = f"寻优成功(SLSQP,迭代{res.nit}次)"
            elif res.fun < objective(x0) + 0.5:
                x_opt = res.x
                opt_status = f"寻优次优解(迭代{res.nit}次,{res.message[:25]})"
            else:
                x_opt = x0
                opt_status = f"寻优回退均匀分配({res.message[:25]})"
                _logger.warning("ChillerGroupOptimizer: SLSQP 未收敛: %s", res.message)
                if alarms_list is not None:
                    alarms_list.append(f"[寻优] SLSQP 未收敛: {res.message}")
        except Exception as exc:
            x_opt = x0
            opt_status = f"寻优异常-回退均匀({type(exc).__name__})"
            _logger.exception("ChillerGroupOptimizer: scipy 异常")
            if alarms_list is not None:
                alarms_list.append(f"[寻优] scipy 异常: {exc}")

        # ── 汇总各机结果 ──────────────────────────────────────────────
        loads = [0.0] * n_total
        powers = [0.0] * n_total
        cops = [0.0] * n_total
        plrs = [0.0] * n_total

        for j, i in enumerate(active_idx):
            L_j = float(np.clip(x_opt[j], lb[j], ub[j]))
            plr_j = float(np.clip(L_j / caps[i], c_min, 1.2))
            cop_j = self._query_cop(t_out, plr_j, t_cw, t_chw)
            loads[i] = round(L_j, 2)
            plrs[i] = round(plr_j, 4)
            cops[i] = round(cop_j, 3)
            powers[i] = round(L_j / max(cop_j, 0.1), 2)

        total_power = round(sum(powers), 2)
        total_load = sum(loads[i] for i in active_idx)
        system_cop = round(total_load / total_power, 3) if total_power > 0 else 0.0
        cost_yuan = round(total_power * float(dt_hr) * float(tou_price_per_kwh), 2)

        self._last_result = {
            "loads": loads,
            "powers": powers,
            "cops": cops,
            "plrs": plrs,
            "total_power_kw": total_power,
            "system_cop": system_cop,
            "status": opt_status,
            "tou_price_per_kwh": float(tou_price_per_kwh),
            "dt_hr": float(dt_hr),
            "cost_yuan": cost_yuan,
        }
        return self._last_result

    def _zero_result(
        self,
        tou_price_per_kwh: float = 1.0,
        dt_hr: float = 1.0,
    ) -> dict[str, Any]:
        """零负荷时返回全零结果，避免空判断。"""
        n_total = len(self.unit_caps_kw)
        return {
            "loads": [0.0] * n_total,
            "powers": [0.0] * n_total,
            "cops": [0.0] * n_total,
            "plrs": [0.0] * n_total,
            "total_power_kw": 0.0,
            "system_cop": 0.0,
            "status": "机组未启用",
            "tou_price_per_kwh": float(tou_price_per_kwh),
            "dt_hr": float(dt_hr),
            "cost_yuan": 0.0,
        }


__all__ = ["ChillerGroupOptimizer"]
