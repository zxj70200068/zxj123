# 冷站群控节能平台

基于负荷预测与非线性优化的冷站群控节能平台 (a chiller-plant supervisory control platform built on local load forecasting + non-linear chiller dispatch + a hard safety supervisor; **LLM does NOT participate in the control loop**).

## Quick start

The sandbox uses pyenv with Python 3.11.15. Export the toolchain, install dependencies, run the test suite, regenerate the load forecaster, and (optionally, on a host with a display) launch the desktop dashboard:

```bash
export PYENV_VERSION=3.11.15
export PATH=/opt/toolchains/.pyenv/shims:$PATH

python3.11 -m pip install -r requirements.txt
python3.11 -m pytest -q
python3.11 -m train.training_pipeline --output models/saved/load_forecast_lr.joblib

# Desktop UI: only when an X11 / Wayland display is available; the file is
# guarded by `if __name__ == "__main__":`, so importing it is always safe.
python3.11 -m ui.dashboard.main_window
```

`models/saved/load_forecast_lr.joblib` ships as a small placeholder model trained on a synthetic dataset. Re-running the training pipeline regenerates it deterministically and updates `load_forecast_lr.metadata.json`.

## Directory map

The project follows a clean four-layer split: `core/` (physics, optimizer, control chain, safety supervisor, reporting), `services/` (UI-facing facade with `simulation_service`, `optimization_service`, `control_service`, `reporting_service`), `models/` + `prediction/` + `train/` (the offline-train / online-predict load-forecasting stack), `adapters/` (BACnet / Modbus / MQTT skeletons), `ui/dashboard/` (Tkinter front-end that imports only from `services/`), `data/configs/` (defaults, presets, `STRATEGY_REGISTRY = {'rule', 'mpc'}`), and `tests/` (pytest suite, including no-LLM-in-control regressions). The original 5082-line single-file Tkinter app is frozen as `legacy/main_ui_legacy.py` for read-only reference. Full module-by-module mapping, deletion list, retained-and-hardened list, control-chain diagram, deployment topology, and the next-round refactor priorities are in [REFACTOR_NOTES.md](./REFACTOR_NOTES.md).

## Contribution rule

**LLM 不得参与控制链** — LLM must never enter the control loop. The control chain (`Prediction → Optimization → Rule → Safety → Execution`) is fully local and deterministic, anchored by `core/safety/supervisor.py::SafetySupervisor` as the final hard gate. LLM use is **only** allowed in the reporting / Copilot path under `services/reporting_service.py` and `core/reporting/` (`llm_client.summarize`, `report_agent`). Two regression tests (`tests/test_no_llm_in_control.py`, `tests/test_no_llm_in_control_v2.py`) and the `STRATEGY_REGISTRY` allow-list enforce this.
