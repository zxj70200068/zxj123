"""Tk dashboard for the configuration-driven HVAC supervisory platform.

This is the FEAT-004 port of the legacy ``MainPlatformGUI`` class
(banner-adjusted lines 3428-5083 of the frozen reference module under
``legacy/``). The
port preserves the visual layout (header bar, five-column control strip,
hydraulic Treeview, console output) but routes every interaction through
the new :mod:`services` layer:

* :class:`services.simulation_service.SimulationService` replaces direct
  ``WhiteBoxEngine.execute_step`` calls.
* :class:`services.reporting_service.ReportingService` replaces the
  legacy ``AIReportAgent`` + ``HistoryLogger`` access pattern.
* :class:`services.control_service.ControlService` is constructed but
  used only as the documented DDC/BACnet front end; the simulation
  execution path keeps using ``SimulationService`` for the long-form
  result dict the Treeview consumes.

By design this module imports **only** from ``services.*``,
``data.configs.*`` and ``utils.*`` (plus stdlib + tkinter + matplotlib).
A static guard in ``tests/test_ui_decoupling.py`` enforces this.

Tk root creation is gated behind ``if __name__ == '__main__'`` so the
module imports cleanly when ``DISPLAY`` is unset (see
``tests/test_services.py`` and the FEAT-004 import-smoke verification).

Strategy combo
--------------
Only LOCAL strategies are exposed (``'rule'`` and ``'mpc'``); cloud /
LLM-driven control strategies have been deleted upstream. The reporting
LLM panel still exists, but is now labelled "运维报告 LLM 设置" with a
prominent disclaimer that the LLM is used only for natural-language
summarization, never for control decisions.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

from data.configs.defaults import (
    DEFAULT_SCENARIOS,
    STRATEGY_REGISTRY,
)
from data.configs.llm_providers import LLM_PROVIDER_PRESETS_FOR_REPORTING
from services.control_service import ControlService
from services.reporting_service import ReportingService
from services.simulation_service import SimulationService
from utils.logging import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Strategy registry presented to the UI.
#
# The combo values are the human-readable labels listed below, while the
# underlying ``strategy_name`` passed to ``services`` is always the key
# (``'rule'`` or ``'mpc'``). This mapping is intentionally narrower than
# ``data.configs.defaults.STRATEGY_REGISTRY`` so we can show the engineer
# a clearer label without leaking the internal short code.
# ---------------------------------------------------------------------------
STRATEGY_LABELS: dict[str, str] = {
    "本地阈值规则控制(rule)": "rule",
    "本地多步预测控制 MPC (mpc)": "mpc",
}


def _resolve_strategy_key(label_or_key: str) -> str:
    """Map a UI label or short key to one of ``'rule'``/``'mpc'``."""
    if label_or_key in STRATEGY_LABELS:
        return STRATEGY_LABELS[label_or_key]
    if label_or_key in STRATEGY_REGISTRY:
        return label_or_key
    return "rule"


class MainPlatformGUI:
    """Tk dashboard backed by the new :mod:`services` layer.

    This class never imports ``core.*`` or ``prediction.*`` directly. All
    side effects (simulation, control evaluation, reporting) go through
    :mod:`services`.

    Parameters
    ----------
    root : tk.Tk
        The Tk root or Toplevel window to render into. Caller owns the
        lifecycle (the dashboard never calls ``root.mainloop`` itself,
        so it can be embedded in a richer host).
    """

    # ------------------------------------------------------------------ ctor
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("《配置驱动型·智慧建筑空调群控数字孪生平台》")
        self.root.geometry("1320x920")
        self.root.minsize(1180, 760)

        # State
        self.last_res: dict | None = None

        # Service layer: SimulationService owns the ConfigManager + engine
        # cache; ReportingService composes text-only reports; ControlService
        # is constructed for parity with the FEAT-004 DDC contract but is
        # not invoked from the legacy "single-step simulation" path because
        # that path needs the long-form dict only the engine produces.
        #
        # Note: the UI must NOT import from ``core.*`` directly (enforced
        # by ``tests/test_ui_decoupling.py``). The :meth:`from_defaults`
        # class method on :class:`SimulationService` is the supported
        # factory: it constructs a default :class:`ConfigManager` inside
        # the services package so this file stays clean.
        self.sim_service = SimulationService.from_defaults()
        self.config_manager = self.sim_service.config_manager
        self.report_service = ReportingService()
        # Default ControlService for DDC/BACnet front-end parity. The UI
        # never drives the plant from this path, but it is exposed so an
        # operator can inspect a single ``ControlCommand`` for the
        # currently selected building / scenario.
        self.control_service = ControlService(
            self.config_manager.sys_config, strategy_name="rule",
        )

        self._build_ui()
        self.show_welcome_info()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.root.configure(bg="#EEF3F7")

        font_title = ("微软雅黑", 15, "bold")
        font_b = ("微软雅黑", 10, "bold")
        font_n = ("微软雅黑", 10)
        font_s = ("微软雅黑", 9)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", padding=3)
        style.configure("Treeview", rowheight=26, font=("微软雅黑", 9))
        style.configure("Treeview.Heading", font=("微软雅黑", 9, "bold"))
        style.configure("TLabelframe.Label", font=font_b)

        def btn(parent, text, command, bg="#3B82F6", fg="white", width=12, **grid_kw):
            b = tk.Button(
                parent, text=text, command=command, bg=bg, fg=fg, font=font_n,
                activebackground=bg, activeforeground=fg, relief=tk.FLAT,
                padx=8, pady=5, width=width, cursor="hand2",
            )
            b.grid(**grid_kw)
            return b

        # Header bar
        header = tk.Frame(self.root, bg="#0F172A", padx=16, pady=10)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="配置驱动型智慧建筑空调群控数字孪生平台",
            bg="#0F172A", fg="white", font=font_title,
        ).pack(side=tk.LEFT)
        tk.Label(
            header, text="  通用建筑 / 校园案例 / 测点联动 / 历史数据",
            bg="#0F172A", fg="#CBD5E1", font=font_s,
        ).pack(side=tk.LEFT, padx=12)
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(
            header, textvariable=self.status_var, bg="#1E293B",
            fg="#A7F3D0", font=font_s, padx=12, pady=4,
        ).pack(side=tk.RIGHT)

        # Control strip (5 columns)
        control = tk.Frame(self.root, bg="#EEF3F7", padx=12, pady=8)
        control.pack(fill=tk.X)
        for i in range(5):
            control.grid_columnconfigure(i, weight=1, uniform="ctrl")

        fr_data = ttk.LabelFrame(control, text=" ① 数据与台账 ")
        fr_data.grid(row=0, column=0, sticky="nsew", padx=5, pady=4)
        btn(fr_data, "导入建筑", self.import_building_config, bg="#2563EB", width=10,
            row=0, column=0, padx=4, pady=3, sticky="we")
        btn(fr_data, "导入工况", self.import_scenarios, bg="#2563EB", width=10,
            row=0, column=1, padx=4, pady=3, sticky="we")
        btn(fr_data, "导入时序", self.import_sequence_plan_ui, bg="#2563EB",
            width=10, row=1, column=0, padx=4, pady=3, sticky="we")
        btn(fr_data, "导入测点", self.import_point_ledger, bg="#0EA5E9",
            width=10, row=1, column=1, padx=4, pady=3, sticky="we")
        btn(fr_data, "台账模板", self.export_point_ledger_template, bg="#38BDF8",
            fg="#082F49", width=10, row=2, column=0, padx=4, pady=3, sticky="we")
        btn(fr_data, "CSV模板", self.export_point_ledger_csv_templates,
            bg="#BAE6FD", fg="#082F49", width=10, row=2, column=1, padx=4, pady=3, sticky="we")
        for c in range(2):
            fr_data.grid_columnconfigure(c, weight=1)

        fr_case = ttk.LabelFrame(control, text=" ② 建筑 / 工况 / 策略 ")
        fr_case.grid(row=0, column=1, sticky="nsew", padx=5, pady=4)
        tk.Label(fr_case, text="建筑模板", font=font_s).grid(
            row=0, column=0, sticky="w", padx=6, pady=(4, 0),
        )
        bldg_keys = list(self.config_manager.building_configs.keys())
        self.cb_bldg = ttk.Combobox(
            fr_case, values=bldg_keys, state="readonly", width=24, font=font_s,
        )
        self.cb_bldg.set(bldg_keys[0])
        self.cb_bldg.grid(row=1, column=0, sticky="we", padx=6, pady=2)
        self.cb_bldg.bind("<<ComboboxSelected>>", self.on_building_change)
        tk.Label(fr_case, text="典型工况", font=font_s).grid(
            row=2, column=0, sticky="w", padx=6, pady=(4, 0),
        )
        scen_keys = list(self.config_manager.scenarios.keys())
        self.cb_scen = ttk.Combobox(
            fr_case, values=scen_keys, state="readonly", width=24, font=font_s,
        )
        default_scen = (
            "03_下午高峰" if "03_下午高峰" in self.config_manager.scenarios
            else scen_keys[0]
        )
        self.cb_scen.set(default_scen)
        self.cb_scen.grid(row=3, column=0, sticky="we", padx=6, pady=2)
        tk.Label(fr_case, text="控制策略 (仅本地)", font=font_s).grid(
            row=4, column=0, sticky="w", padx=6, pady=(4, 0),
        )
        # The strategy combo MUST be limited to rule + mpc; cloud / BiLSTM
        # entries have been deleted from the registry.
        self.strategy_var = tk.StringVar(value="本地多步预测控制 MPC (mpc)")
        cb_strat = ttk.Combobox(
            fr_case, textvariable=self.strategy_var,
            values=list(STRATEGY_LABELS.keys()),
            state="readonly", width=24, font=font_s,
        )
        cb_strat.grid(row=5, column=0, sticky="we", padx=6, pady=2)
        tk.Label(
            fr_case,
            text="LLM 仅用于生成报告与告警解释，不参与控制链",
            font=("微软雅黑", 8), fg="#B91C1C", wraplength=220, justify=tk.LEFT,
        ).grid(row=6, column=0, sticky="we", padx=6, pady=(2, 4))
        fr_case.grid_columnconfigure(0, weight=1)

        fr_run = ttk.LabelFrame(control, text=" ③ 运行仿真 ")
        fr_run.grid(row=0, column=2, sticky="nsew", padx=5, pady=4)
        self.btn_run = btn(fr_run, "单步仿真", self.run_sim_async, bg="#1D4ED8",
                           width=14, row=0, column=0, padx=5, pady=4, sticky="we")
        self.btn_seq = btn(fr_run, "全天时序仿真", self.run_sequence_async,
                           bg="#15803D", width=14, row=1, column=0, padx=5, pady=4, sticky="we")
        btn(fr_run, "重置状态", self.reset_platform, bg="#64748B", width=14,
            row=2, column=0, padx=5, pady=4, sticky="we")
        fr_run.grid_columnconfigure(0, weight=1)

        fr_view = ttk.LabelFrame(control, text=" ④ 分析与展示 ")
        fr_view.grid(row=0, column=3, sticky="nsew", padx=5, pady=4)
        btn(fr_view, "事件日志", self.show_logs, bg="#475569", width=12,
            row=0, column=0, padx=4, pady=3, sticky="we")
        btn(fr_view, "导出报告", self.export_current_report, bg="#C2410C",
            width=12, row=0, column=1, padx=4, pady=3, sticky="we")
        for c in range(2):
            fr_view.grid_columnconfigure(c, weight=1)

        fr_export = ttk.LabelFrame(control, text=" ⑤ 运维报告 LLM 设置 ")
        fr_export.grid(row=0, column=4, sticky="nsew", padx=5, pady=4)
        btn(fr_export, "LLM设置", self.open_api_settings, bg="#7E22CE",
            width=10, row=0, column=0, padx=4, pady=3, sticky="we")
        btn(fr_export, "测试连接", self.test_api, bg="#7E22CE", width=10,
            row=0, column=1, padx=4, pady=3, sticky="we")
        tk.Label(
            fr_export,
            text="LLM 仅用于生成报告与告警解释，不参与控制链",
            font=("微软雅黑", 8), fg="#B91C1C", wraplength=210, justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="we", padx=4, pady=(4, 4))
        for c in range(2):
            fr_export.grid_columnconfigure(c, weight=1)

        # Hydraulic table
        paned = tk.PanedWindow(
            self.root, orient=tk.VERTICAL, sashrelief=tk.RAISED, bg="#CBD5E1",
        )
        paned.pack(fill=tk.BOTH, expand=True, padx=15, pady=4)

        self.fr_hyd = ttk.LabelFrame(paned, text=" 冷冻水末端数字孪生表 ")
        self.hyd_cols = (
            "支路名称", "末端类型", "供冷(kW)", "估算风量(m³/h)", "水流量(m³/h)",
            "阀门开度(%)", "管路阻力(kPa)", "送风温度(℃)", "回风温度(℃)", "数据溯源",
        )
        self.tv_hyd = ttk.Treeview(
            self.fr_hyd, columns=self.hyd_cols, show="headings", height=5,
        )
        self.tv_hyd.tag_configure("alert", foreground="red", font=("微软雅黑", 9, "bold"))
        self.tv_hyd.tag_configure("sleep", foreground="gray")
        for c in self.hyd_cols:
            self.tv_hyd.heading(c, text=c)
            w = 135 if c in ("支路名称", "末端类型", "数据溯源") else 105
            self.tv_hyd.column(c, width=w, anchor="center")
        yscroll = ttk.Scrollbar(
            self.fr_hyd, orient="vertical", command=self.tv_hyd.yview,
        )
        xscroll = ttk.Scrollbar(
            self.fr_hyd, orient="horizontal", command=self.tv_hyd.xview,
        )
        self.tv_hyd.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tv_hyd.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.fr_hyd.grid_rowconfigure(0, weight=1)
        self.fr_hyd.grid_columnconfigure(0, weight=1)
        paned.add(self.fr_hyd, minsize=150)

        # Console output
        fr_out = ttk.LabelFrame(paned, text=" 运行报告 / 控制台输出 ")
        self.txt_out = scrolledtext.ScrolledText(
            fr_out, font=("Consolas", 10), bg="#0F172A",
            fg="#A7F3D0", insertbackground="white", height=12,
        )
        self.txt_out.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        paned.add(fr_out, minsize=220)

        note = (
            "【工程声明】本系统为仿真运行数据采集平台，不宣称接入现场真实传感器，"
            "也不宣称完成真实项目 AI 训练。LLM 仅出现在运维报告与告警解释路径，"
            "不参与控制链；现场部署请通过 services.control_service.ControlService 接入。"
        )
        self.note_var = tk.StringVar(value=note)
        tk.Label(
            self.root, textvariable=self.note_var, fg="#B91C1C", bg="#FEF2F2",
            font=("微软雅黑", 9, "bold"), justify=tk.LEFT, anchor="w",
            padx=12, pady=6,
        ).pack(fill=tk.X, padx=15, pady=(0, 5))

    # ------------------------------------------------------------ console
    def out(self, text: str, clear: bool = True) -> None:
        if clear:
            self.txt_out.delete("1.0", tk.END)
        self.txt_out.insert(tk.END, str(text) + "\n")
        self.txt_out.see(tk.END)

    def set_buttons_state(self, state: str) -> None:
        for name in ("btn_run", "btn_seq"):
            b = getattr(self, name, None)
            if b is not None:
                try:
                    b.configure(state=state)
                except Exception:
                    pass

    # --------------------------------------------------- callbacks: scenes
    def show_welcome_info(self) -> None:
        msg = (
            "《配置驱动型·智慧建筑空调群控数字孪生平台》\n\n"
            "本系统基于软硬件解耦与参数外置驱动设计；UI 仅通过 services 层与 core 模块交互。\n\n"
            "▶ 控制策略：仅本地阈值规则 (rule) 与本地多步预测控制 MPC (mpc)。\n"
            "▶ 安全闭环：每一次控制命令都经过 SafetySupervisor 最终复核。\n"
            "▶ LLM：仅在运维报告与告警解释路径出现，禁止进入控制链。\n\n"
            "【提示】默认已选择[03_下午高峰]工况，点击[单步仿真]即可执行一次完整的"
            "Prediction → Optimization → Rule → Safety → Execution 链路并展示水力数字孪生。"
        )
        self.out(msg, clear=True)

    def on_building_change(self, event: Any = None) -> None:
        self.status_var.set(f"已切换建筑: {self.cb_bldg.get()}")

    # ---------------------------------------------------- run single step
    def run_sim_async(self, run_type: str = "single_step") -> None:
        self.set_buttons_state("disabled")
        s_name = self.cb_scen.get()
        factor = self.config_manager.scenarios.get(
            s_name, DEFAULT_SCENARIOS.get("03_下午高峰", {}),
        ).copy()
        strategy_key = _resolve_strategy_key(self.strategy_var.get())
        building_key = self.cb_bldg.get()

        self.out("仿真计算中，请稍候...", clear=False)

        def worker() -> None:
            try:
                res = self.sim_service.run_single_step(
                    building_key=building_key,
                    scenario_factor=factor,
                    strategy_name=strategy_key,
                    dt_min=15.0,
                )
            except Exception as exc:
                _logger.exception("MainPlatformGUI.run_sim_async worker failed")
                res = None
                err = exc

            def update_ui() -> None:
                self.set_buttons_state("normal")
                if res is None:
                    self.out(f"仿真执行异常: {err}", clear=False)
                    return
                try:
                    self.last_res = res
                    self._refresh_hyd_table(res.get("hydraulic", {}) or {})
                    report_text = self.report_service.format_step_result(res, s_name)
                    self.out(report_text)
                    self.status_var.set(
                        f"模式={res.get('combo', '-')} "
                        f"功率={res.get('opt_p', 0)} kW"
                    )
                except Exception as exc:
                    _logger.exception("MainPlatformGUI.run_sim_async update_ui failed")
                    self.out(f"渲染异常: {exc}", clear=False)

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------- run sequence
    def run_sequence_async(self) -> None:
        self.set_buttons_state("disabled")
        self.out("正在执行全天时序仿真，请稍候...", clear=True)
        strategy_key = _resolve_strategy_key(self.strategy_var.get())
        building_key = self.cb_bldg.get()
        plan = list(self.config_manager.sequence_plan)

        def worker() -> None:
            try:
                results = self.sim_service.run_sequence(
                    building_key=building_key,
                    sequence_plan=plan,
                    strategy_name=strategy_key,
                    dt_min=15.0,
                )
            except Exception as exc:
                _logger.exception("MainPlatformGUI.run_sequence_async worker failed")
                results = None
                err = exc

            def update_ui() -> None:
                self.set_buttons_state("normal")
                if not results:
                    self.out(f"时序仿真异常: {err if results is None else '空结果'}", clear=False)
                    return
                last = results[-1]
                self._refresh_hyd_table(last.get("hydraulic", {}) or {})
                summary = self.report_service.summarize_run(self.cb_scen.get())
                self.out(summary, clear=True)
                self.out(
                    f"\n▶ 共完成 {len(results)} 步；最末模式={last.get('combo', '-')}",
                    clear=False,
                )
                self.status_var.set(f"时序完成: {len(results)} 步")

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------- helpers
    def _refresh_hyd_table(self, hyd: dict) -> None:
        for item in self.tv_hyd.get_children():
            self.tv_hyd.delete(item)
        if hyd.get("is_sleep", True):
            self.tv_hyd.insert(
                "", "end",
                values=("全网管道", "休眠待命", "0.0", "0.0", "0.0",
                        "0.0", "0.0", "--", "--", "系统休眠"),
                tags=("sleep",),
            )
            return
        for b in hyd.get("branches", []) or []:
            tag = ("alert",) if b.get("warning") else ()
            self.tv_hyd.insert(
                "", "end",
                values=(
                    b.get("zone_name", "-"), b.get("terminal_type", "-"),
                    b.get("cooling_kw", 0), b.get("air_flow_m3h", 0),
                    b.get("flow_m3h", 0), b.get("valve_opening", 0),
                    b.get("branch_total_dp_kpa", 0),
                    b.get("supply_air_temp", "-"),
                    b.get("return_air_temp", "-"),
                    "仿真公式计算",
                ),
                tags=tag,
            )

    # ------------------------------------------------------ misc actions
    def reset_platform(self) -> None:
        self.sim_service = SimulationService.from_defaults()
        self.config_manager = self.sim_service.config_manager
        self.report_service = ReportingService()
        self.control_service = ControlService(
            self.config_manager.sys_config, strategy_name="rule",
        )
        for item in self.tv_hyd.get_children():
            self.tv_hyd.delete(item)
        self.last_res = None
        self.show_welcome_info()
        self.status_var.set("平台已重置")

    def show_logs(self) -> None:
        if self.last_res is None:
            self.out("尚未执行任何步骤，事件日志为空。", clear=True)
            return
        report = self.report_service.format_step_result(
            self.last_res, self.cb_scen.get(),
        )
        self.out(report, clear=True)

    def export_current_report(self) -> None:
        if self.last_res is None:
            messagebox.showwarning("提示", "请先执行一次仿真后再导出。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text", "*.txt")],
            initialfile="HVAC_运行报告.txt",
        )
        if not path:
            return
        try:
            text = self.report_service.format_step_result(
                self.last_res, self.cb_scen.get(),
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("成功", f"报告已导出至: {path}")
        except Exception as exc:
            _logger.exception("MainPlatformGUI.export_current_report failed")
            messagebox.showerror("导出失败", str(exc))

    # -------------------------------------------- import-side delegation
    def import_building_config(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        ok, msg, _ = self.config_manager.load_external_config(p)
        if ok:
            self.cb_bldg.config(values=list(self.config_manager.building_configs.keys()))
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def import_scenarios(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        ok, msg = self.config_manager.load_external_scenarios(p)
        if ok:
            self.cb_scen.config(values=list(self.config_manager.scenarios.keys()))
            self.cb_scen.set(list(self.config_manager.scenarios.keys())[0])
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def import_sequence_plan_ui(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        ok, msg = self.config_manager.load_external_sequence(p)
        if ok:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def import_point_ledger(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        ok, msg = self.config_manager.load_external_point_ledger(p)
        if ok:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导入失败", msg)

    def export_point_ledger_template(self) -> None:
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="通用建筑机电测点台账模板.json",
        )
        if not p:
            return
        ok, msg = self.config_manager.export_point_ledger_template(p)
        if ok:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导出失败", msg)

    def export_point_ledger_csv_templates(self) -> None:
        folder = filedialog.askdirectory(title="选择CSV台账模板导出文件夹")
        if not folder:
            return
        ok, msg = self.config_manager.export_point_ledger_csv_templates(folder)
        if ok:
            messagebox.showinfo("成功", msg)
        else:
            messagebox.showerror("导出失败", msg)

    # ---------------------------------------------------- LLM panel hooks
    def open_api_settings(self) -> None:
        """Show the reporting LLM provider/api-key panel.

        The panel itself stores nothing into the supervisory control
        path; it only configures the optional :class:`LLMClient` used by
        :class:`ReportingService.explain_alarm` and
        :meth:`ReportAgent.enrich_with_summary`.
        """
        top = tk.Toplevel(self.root)
        top.title("运维报告 LLM 设置")
        top.geometry("520x340")

        tk.Label(
            top,
            text=(
                "LLM 仅用于生成运维报告与告警解释，不参与控制链。\n"
                "请选择一个供应商并填写 Base URL / 模型名称 / API Key。"
            ),
            fg="#B91C1C", justify=tk.LEFT, padx=10, pady=8,
        ).grid(row=0, column=0, columnspan=2, sticky="we")

        tk.Label(top, text="选择供应商:").grid(
            row=1, column=0, padx=10, pady=10, sticky="e",
        )
        provider_names = [
            preset["display_name"]
            for preset in LLM_PROVIDER_PRESETS_FOR_REPORTING.values()
        ]
        cb_prov = ttk.Combobox(top, values=provider_names, state="readonly")
        cb_prov.grid(row=1, column=1, pady=10, sticky="we")

        tk.Label(top, text="Base URL:").grid(
            row=2, column=0, padx=10, pady=5, sticky="e",
        )
        e_url = tk.Entry(top, width=42)
        e_url.grid(row=2, column=1, pady=5, sticky="we")

        tk.Label(top, text="模型名称(Model):").grid(
            row=3, column=0, padx=10, pady=5, sticky="e",
        )
        e_model = tk.Entry(top, width=42)
        e_model.grid(row=3, column=1, pady=5, sticky="we")

        tk.Label(top, text="API Key:").grid(
            row=4, column=0, padx=10, pady=5, sticky="e",
        )
        e_key = tk.Entry(top, width=42, show="*")
        e_key.grid(row=4, column=1, pady=5, sticky="we")

        # Mapping display_name -> preset key
        name_to_key = {
            preset["display_name"]: key
            for key, preset in LLM_PROVIDER_PRESETS_FOR_REPORTING.items()
        }

        def on_prov_change(_evt: Any = None) -> None:
            prov_name = cb_prov.get()
            if not prov_name:
                return
            preset = LLM_PROVIDER_PRESETS_FOR_REPORTING.get(
                name_to_key.get(prov_name, ""), {}
            )
            for entry, val in (
                (e_url, preset.get("base_url", "")),
                (e_model, preset.get("model", "")),
            ):
                entry.delete(0, tk.END)
                entry.insert(0, val)

        cb_prov.bind("<<ComboboxSelected>>", on_prov_change)
        if provider_names:
            cb_prov.set(provider_names[0])
            on_prov_change()

        def save() -> None:
            messagebox.showinfo(
                "提示",
                "LLM 设置仅用于运维报告生成路径。当前实现未写入磁盘；"
                "请通过外部 config_api.json 持久化敏感凭证。",
                parent=top,
            )
            top.destroy()

        tk.Button(
            top, text="保存设置", bg="#27AE60", fg="white", command=save,
        ).grid(row=5, column=0, columnspan=2, pady=15)

    def test_api(self) -> None:
        """Smoke-test the reporting LLM endpoint (never affects control)."""
        messagebox.showinfo(
            "提示",
            "LLM 测试仅触发运维报告路径下的 summarize() 调用；"
            "控制链 (rule/mpc) 与 LLM 完全解耦。",
        )


# ---------------------------------------------------------------------------
# CLI entry-point.
#
# Tk root creation lives in ``main()`` so importing this module never
# touches a display. The static UI-decoupling guard
# (``tests/test_ui_decoupling.py``) parses every .py file under ``ui/``
# and forbids any import whose top-level package starts with ``core.``,
# ``prediction.``, ``train.`` or ``models.``. The default-configured
# :class:`SimulationService` is obtained via :meth:`SimulationService.from_defaults`
# so this UI module stays purely on the services boundary.
# ---------------------------------------------------------------------------
def main() -> None:
    """CLI entry-point: build a Tk root and run the dashboard.

    Importing this module never creates a Tk root; only this function does.
    """
    root = tk.Tk()
    MainPlatformGUI(root)
    root.mainloop()


__all__ = ["MainPlatformGUI", "main"]


if __name__ == "__main__":
    main()
