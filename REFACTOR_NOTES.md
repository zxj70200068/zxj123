# 冷站群控节能平台 重构笔记 (REFACTOR_NOTES)

本笔记记录从 5082 行单文件 Tkinter 桌面端 (`main_ui_optimized (4).py`) 到分层工业控制平台的全部结构性变更。原文件已冻结为 `legacy/main_ui_legacy.py`，仅作只读参考，不被新代码导入。

---

## 1. 重构后的完整目录结构

以下为执行 `tree -L 3 -I '__pycache__|.git|legacy|.agents|.ruff_cache|.pytest_cache' .` 的真实输出 (FEAT-005 验证时刻)：

```
.
├── adapters
│   ├── bacnet
│   │   ├── base.py
│   │   └── __init__.py
│   ├── __init__.py
│   ├── modbus
│   │   ├── base.py
│   │   └── __init__.py
│   └── mqtt
│       ├── base.py
│       └── __init__.py
├── app_error.log
├── core
│   ├── config.py
│   ├── control
│   │   ├── control_chain.py
│   │   ├── __init__.py
│   │   ├── low_sensor_mode.py
│   │   └── strategies.py
│   ├── economics.py
│   ├── history.py
│   ├── __init__.py
│   ├── optimizer
│   │   ├── chiller_group.py
│   │   └── __init__.py
│   ├── physics
│   │   ├── hydraulic.py
│   │   ├── __init__.py
│   │   ├── simulation_engine.py
│   │   ├── terminal_linkage.py
│   │   └── thermal.py
│   ├── prediction
│   │   └── __init__.py
│   ├── reporting
│   │   ├── __init__.py
│   │   ├── llm_client.py
│   │   └── report_agent.py
│   ├── safety
│   │   ├── __init__.py
│   │   └── supervisor.py
│   └── simulation
│       ├── engine.py
│       └── __init__.py
├── data
│   ├── configs
│   │   ├── defaults.py
│   │   ├── __init__.py
│   │   └── llm_providers.py
│   ├── history
│   │   └── __init__.py
│   ├── __init__.py
│   └── sensors
│       └── __init__.py
├── models
│   ├── equipment.py
│   ├── __init__.py
│   ├── load_predictor.py
│   └── saved
│       ├── __init__.py
│       ├── load_forecast_lr.joblib
│       └── load_forecast_lr.metadata.json
├── prediction
│   ├── __init__.py
│   └── load_forecast_service.py
├── pyproject.toml
├── requirements.txt
├── services
│   ├── control_service.py
│   ├── __init__.py
│   ├── optimization_service.py
│   ├── reporting_service.py
│   └── simulation_service.py
├── tests
│   ├── __init__.py
│   ├── test_chiller_optimizer.py
│   ├── test_control_chain.py
│   ├── test_load_forecast.py
│   ├── test_low_sensor_mode.py
│   ├── test_no_llm_in_control.py
│   ├── test_no_llm_in_control_v2.py
│   ├── test_physics_thermal.py
│   ├── test_safety_supervisor.py
│   ├── test_services.py
│   ├── test_skeleton.py
│   └── test_ui_decoupling.py
├── train
│   ├── datasets
│   │   └── __init__.py
│   ├── feature_engineering.py
│   ├── __init__.py
│   ├── model_export.py
│   └── training_pipeline.py
├── ui
│   ├── charts
│   │   └── __init__.py
│   ├── controls
│   │   └── __init__.py
│   ├── dashboard
│   │   ├── __init__.py
│   │   └── main_window.py
│   └── __init__.py
└── utils
    ├── __init__.py
    ├── logging.py
    └── paths.py

28 directories, 77 files
```

`legacy/main_ui_legacy.py` 不在上述视图中，但物理存在于仓库根目录下，作为只读参考保留。

---

## 2. 新的模块拆分

下表给出每个新模块吸收的 legacy 类 / 大段代码 (行号引用 `legacy/main_ui_legacy.py`)。

| 新模块 | 吸收的 legacy 类 / 代码块 | 说明 |
| --- | --- | --- |
| `core/config.py` | `ConfigManager` (L523-854) | 移除所有 Tk 依赖，纯字典/JSON 配置管理。 |
| `core/history.py` | `HistoryLogger` (L317-522) | 40 列 CSV 写入 (`data/history/history_log.csv`)，被训练管线复用。 |
| `core/economics.py` | `LCCEstimator` (L2037-2074) | LCC、TOU 价格、电价分时计算。 |
| `core/physics/hydraulic.py` | `HydraulicNetworkModel` (L855-1014) | 二级泵网络、速度平方阻力近似。 |
| `core/physics/terminal_linkage.py` | `TerminalPointLinkageModel` (L1015-1258) | 末端点位与水力的耦合。 |
| `core/physics/thermal.py` | `RoomRCModel` + `ThermalBuffer` (L2010-2036) | 房间 RC 热模型 + 缓冲。 |
| `core/physics/simulation_engine.py` | `PhysicsSimulationEngine` (L1259-1747) | 单步物理仿真步进。 |
| `core/optimizer/chiller_group.py` | `ChillerGroupOptimizer` (L1782-2009) | **强化**：SLSQP、COP 三维等效修正、防喘振 min PLR、TOU-aware staging cost、大机优先投机、异常回退到均匀分配。 |
| `core/control/strategies.py` | `BaseStrategy` + `RuleBasedStrategy` + `MPCStrategy` (L2896-2960) | **MPC 强化**：horizon、dead\_time\_min、min\_run/min\_stop lockout、switch\_penalty\_yuan、tou\_provider、舒适度+满足率 penalty。 |
| `core/control/control_chain.py` | (新增) | 五段控制链 (Prediction → Optimization → Rule → Safety → Execution)，是 `WhiteBoxEngine.execute_step` 内联策略调度的纯净替代。 |
| `core/control/low_sensor_mode.py` | (新增) | 在传感器缺失/通讯降级时由设计工况反推估计输入向量。 |
| `core/safety/supervisor.py` | (新增；吸收 `WhiteBoxEngine.execute_step` L2272-2278 室温超驰块) | `SafetySupervisor.validate_command` 8 条硬规则 (CHW 范围、泵频范围、机组台数、VRF 需求、min\_run/min\_stop、通讯超时、AI 失败、室温超限)。 |
| `core/simulation/engine.py` | `WhiteBoxEngine` (L2075-2788) | 仅保留状态管理与物理推进；策略调度与安全超驰已外迁。 |
| `core/reporting/llm_client.py` | `LLMClient` (L2789-2895) | **改造**：原 `get_recommendation` (返回控制模式) 已删除，唯一公开方法是 `summarize(state)`，仅生成自然语言运维摘要。 |
| `core/reporting/report_agent.py` | `AIReportAgent` (L3312-3426) | 仅读 `HistoryLogger`，从不返回控制模式；报告内的 `ai_suggested_type` 字段已移除。 |
| `models/equipment.py` | `EquipmentModel` + `EquipmentRegistry` (L1748-1781) | 设备元数据。 |
| `models/load_predictor.py` | (新增) | 包装 sklearn 模型 + metadata，替代 BiLSTM 假调用。 |
| `prediction/load_forecast_service.py` | (新增；替代 `BiLSTMCloudStrategy._call_cloud_bilstm` L3160-3175) | 真实负荷预测服务，从 `models/saved/load_forecast_lr.joblib` 加载 sklearn 模型。 |
| `train/training_pipeline.py` | (新增) | 命令行训练入口：`python -m train.training_pipeline --output ...`. |
| `train/feature_engineering.py` | (新增) | 时序特征构造。 |
| `train/model_export.py` | (新增) | joblib + metadata.json 双写。 |
| `train/datasets/` | (新增) | 数据集加载占位。 |
| `services/simulation_service.py` | `SimulationRunner` (L3216-3311) | UI 入口的仿真服务，UI 仅依赖此层。 |
| `services/optimization_service.py` | `ChillerGroupOptimizer` 调用包装 | 把 SLSQP 调度暴露给 UI / REST。 |
| `services/control_service.py` | (新增) | 装配 `ControlChain` + `SafetySupervisor` + 策略，给 UI 一个统一的 `compute_command(observation) → ControlCommand` 接口。 |
| `services/reporting_service.py` | (新增；吸收 `AIReportAgent` UI 调用) | LLM 仅在此层落地，提供 `summarize_run` / `explain_alarm`。 |
| `ui/dashboard/main_window.py` | `MainPlatformGUI` (L3427-5082) | 纯 Tkinter 仪表板；只 import `services/`，不再 import `core/` 算法层；不再设置 `engine.ui_reference` 反向回指。 |
| `adapters/bacnet/base.py`、`adapters/modbus/base.py`、`adapters/mqtt/base.py` | (新增) | DDC/BAS 抽象骨架，目前为接口占位。 |
| `data/configs/defaults.py` | 顶层 `DEFAULT_SYS_CONFIG` 等 (legacy 文件头部常量) | 默认系统、建筑、场景、序列计划、点位台账、`STRATEGY_REGISTRY = {'rule','mpc'}`、`MODE_LABELS`、`DISPLAY_NAME_MAP`。 |
| `data/configs/llm_providers.py` | 顶层 `PROVIDER_PRESETS` | LLM 服务商预设；标注 "仅用于报告，禁用于控制链"。 |
| `utils/paths.py`、`utils/logging.py` | (新增) | 仓库根定位 + 标准 logging 装配。 |

---

## 3. 删除内容列表

下列代码块在 legacy 文件中存在，但在新代码树中**已彻底移除**。

- **`CloudAIStrategy.decide_mode`** (legacy L2961-3016)：通过 HTTP POST 调用 LLM 端点并解析 JSON 选择控制模式。理由：LLM 控制链禁忌 (输出不确定、延迟不可控、不可审计)。整个 `CloudAIStrategy` 类未在 `core/control/strategies.py` 出现。
- **`BiLSTMCloudStrategy` 整类** (legacy L3017-3215)：硬编码 `https://campus-bilstm.cloud.local/api/v1/predict` 假端点，`_call_cloud_bilstm` 内部用 `random.uniform(0.8, 1.2)` 伪造预测。理由：完全是占位假货，无任何真实模型。已由 `prediction/load_forecast_service.predict_next_load` (sklearn 真模型) 替代。
- **`STRATEGY_REGISTRY` 中所有 cloud / BiLSTM 条目**：legacy 中 registry 含 `cloud_ai` / `bilstm_cloud` 等键。新版 `data/configs/defaults.py::STRATEGY_REGISTRY = {'rule', 'mpc'}`，仅本地策略可选。
- **`WhiteBoxEngine.execute_step` 内联 strategy invocation block** (legacy L2280-2305)：原本在 step 内分支调用 `RuleBasedStrategy` / `MPCStrategy` / `CloudAIStrategy` / `BiLSTMCloudStrategy`。已外迁到 `core/control/control_chain.py::ControlChain.step`。
- **`WhiteBoxEngine.execute_step` 内联室温安全超驰 block** (legacy L2272-2278)：原本在 step 内根据 `t_in > indoor_temp_limit` 强制提模。已外迁为 `SafetySupervisor` 第 8 条规则，统一所有超驰路径。
- **`LLMClient.get_recommendation`** (legacy L2789-2895 内的方法)：原方法把 LLM 输出解析为控制模式，是 LLM-in-control 的另一条隐路径。新版 `core/reporting/llm_client.py::LLMClient` 只有 `summarize(state) -> str`，明确仅生成自然语言摘要供报告使用。
- **`WhiteBoxEngine.ui_reference` 反向回指** (legacy L3445-3450 中由 `MainPlatformGUI` 注入)：UI 实例直接挂在引擎上，引擎反过来调 UI。已删除；新版 UI 通过 `services.simulation_service.SimulationService` 注册一个 `frame_callbacks: list[Callable]` 回调列表，循环边界始终从 service → UI 单向流动。

---

## 4. 保留并强化内容列表

下列模块在重构中**保留并加固**，是平台真正的工业级核心。

### `core/optimizer/chiller_group.py::ChillerGroupOptimizer`

- 求解器：`scipy.optimize.minimize(method='SLSQP')`，多机连续负荷分配。
- COP 三维等效修正：冷却水进水温度 + 冷冻水出水温度 + PLR 三维查表/拟合。
- 防喘振 min PLR：每台机组下限保护，避免低部分负荷区涡流脱流。
- TOU-aware cost：以分时电价直接构造目标函数 (而非单纯 kW 最优)。
- 大机优先投机：相同等效效率下偏向先投运额定容量较大的机组以减少切换。
- 异常回退到均匀分配：SLSQP 不收敛时退化为按设计容量均分，保证决策永远有解。

### `core/control/strategies.py::MPCStrategy`

- 两步前瞻 horizon (`horizon=2`)；可通过构造参数延展。
- `dead_time_min`：模式切换死区时间，抑制频繁切换。
- `min_run_minutes` / `min_stop_minutes` lockout：最小运行 / 最小停机锁定窗口。
- `switch_penalty_yuan`：每次模式切换显式计入目标函数。
- 可注入 `tou_provider`：解耦电价来源 (默认走 `core.economics`)。
- 舒适度 + 满足率 penalty：综合 `t_in` 偏离设定 + 实供冷量与目标的差额。

### 新增工业层

- **五段控制链** (`core/control/control_chain.py`)：见第 5 节图。
- **`SafetySupervisor` 8 条硬规则** (`core/safety/supervisor.py`)：CHW 供水温度范围、泵频范围、`n_chillers` 范围、VRF 需求范围、`min_run`/`min_stop`、通讯超时回退、AI 策略失败回退、室温超限强制提模。
- **`LowSensorMode` 降级输入** (`core/control/low_sensor_mode.py`)：传感器缺失或通讯降级时，由设计工况、时段、占用率反推一个保守但安全的观测向量，使上层决策仍可落地。

### 行为变更说明 (vs legacy)

下列控制链行为相比 legacy 实现已**主动加固**，不是简单的 1:1 移植；任何 PR 触发同样情境时新行为生效：

- **Rule 8 (室温超限) 在低负荷工况更激进**：legacy `WhiteBoxEngine.execute_step` (L2272-2278) 在 `t_in > indoor_temp_limit` 时按 `q_required > th.mid` 决定 `MID` / `LOW`，亦即低负荷条件下可以仅靠 VRF 处理而不启动冷机。新 `SafetySupervisor` 第 8 条永远把 `t_in` 超限升级到至少 `MID` (负荷高于 `th_high` 时升至 `HIGH`)，即便瞬时负荷低也会启动冷机。理由：室温越限属于人体舒适与设备保护红线，不应由 VRF 单独承担恢复责任。运维侧需要知道一次低负荷晚间外扰会触发冷机投运，这与 legacy 行为不同。
- **Rule 6 (`comm_timeout`) / Rule 7 (`ai_failure` LOW fallback)** 现在会把 `n_chillers=0` **以及** `vrf_demand_kw=0.0` 一并清零，使下发到 BACnet 的 `ControlCommand` 在 `mode=LOW` 与 `n_chillers/vrf_demand` 之间不再出现矛盾镜像 (v1 review 第 10 条)。
- **`WhiteBoxEngine.execute_step` 反抖锁定** (`time_in_mode >= lock_req`) 现在被任何 `cmd_obj.overridden=True` 直接绕过，包括方向为 `LOW` 的 supervisor 强制降级 (v1 review 第 2 条)。这意味着通讯中断或 AI 失败发生当步即生效，不再延后到 `min_stop_minutes` 满足之后。
- **控制链异常分支** 现在统一走 `supervisor.validate_command` (v1 review 第 3 条)。即便 `ControlChain.step` 抛出 `Exception`，引擎也会先合成一个 `ControlCommand(mode="LOW", n_chillers=0)` 交给 supervisor 验证一次；若彼时 `t_in` 已越限，rule 8 仍会把模式升至 `MID/HIGH`。仅当 `validate_command` 自身再次抛错时才退回硬编码 `LOW`。
- **`predicted_next_load_kw` 当前是观测点位**：`prediction/load_forecast_service.predict_next_load` 真实推理结果会写入 `engine_state['predicted_next_load_kw']` 供 HistoryLogger 与 UI 读取，但 `RuleBasedStrategy` / `MPCStrategy` / `ChillerGroupOptimizer` 三处目前都没有把它纳入决策。把它接入 MPC 前瞻或规则阈值是第 9 节路线图的下一步动作。

---

## 5. 新控制链流程

```
                      ┌──────────────────────┐
   Sensors / DDC  ───►│   Observation        │
                      │  (raw factor dict)   │
                      └──────────┬───────────┘
                                 │
                       Comm OK?  │  Comm DOWN / sensor missing?
                                 │
                      ┌──────────▼───────────┐
                      │  LowSensorMode.lift  │   (only when degraded)
                      │  -> safe synthesised │
                      │     observation      │
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │  PredictionLayer     │
                      │  predict_next_load   │
                      │  -> predicted_kw     │
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │  RuleLayer           │   (must run first in time:
                      │  strategy.decide_mode│    optimizer only invests
                      │  -> proposed_mode    │    chillers when mode is
                      └──────────┬───────────┘    MID/HIGH)
                                 │
                  proposed_mode in {MID, HIGH}?
                                 │
                      ┌──────────▼───────────┐
                      │  OptimizationLayer   │   (skipped on LOW)
                      │  ChillerGroupOptim.  │
                      │  -> n_chillers, PLRs │
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │  SafetyLayer         │
                      │  Supervisor.validate │
                      │  _command (8 rules)  │
                      │  -> alarms, override │
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │  ExecutionLayer      │
                      │  ControlCommand      │
                      └──────────┬───────────┘
                                 │
                                 ▼
                       DDC / BACnet / Modbus
                       (adapters/<protocol>/base.py)
```

> 时序备注：`ControlChain.step` 中 RuleLayer 必须先于 OptimizationLayer 在时间轴上运行，因为优化层只在 RuleLayer 提议为 `MID` 或 `HIGH` 时才计算冷机投运组合；这一点已在 `core/control/control_chain.py` 顶层 docstring 显式声明。

---

## 6. 新数据流

```
[Sensors / DDC]
      │
      ▼
[HistoryLogger]  ───► data/history/history_log.csv  (40 列)
      │
      ▼
[train/training_pipeline.py]  (CLI: python -m train.training_pipeline --output ...)
      │   feature_engineering.py
      │   model_export.py
      ▼
models/saved/load_forecast_lr.joblib
models/saved/load_forecast_lr.metadata.json
      │
      ▼
[prediction/load_forecast_service.predict_next_load]
      │
      ▼
[core.control.control_chain.ControlChain]
      │
      ▼
[core.safety.supervisor.SafetySupervisor]
      │
      ▼
[adapters/<protocol>/base.py]  →  DDC / BAS
```

模型再训练只需重跑训练管线；运行时不接任何外部云端预测端点。

---

## 7. 新部署架构

四层物理部署，**LLM 永不进入控制链**：

```
┌──────────────────────────────────────────────────────────────────┐
│ 云端 (Cloud)                                                      │
│   - 模型训练: train/training_pipeline.py 离线批训练                 │
│   - 数据分析: 历史 CSV 仓库 / BI                                    │
│   - LLM 服务商: 仅供边缘网关 reporting 通道访问                      │
└──────────────────────────────────────────────────────────────────┘
                              │ joblib 模型文件 / 摘要请求 (HTTPS)
┌──────────────────────────────────────────────────────────────────┐
│ 边缘网关 (Edge Gateway, 7×24 实时控制)                              │
│   - prediction/load_forecast_service.py     (sklearn 推理)         │
│   - core/control/control_chain.py           (五段控制链)            │
│   - core/control/strategies.py::MPCStrategy (本地 MPC)             │
│   - core/optimizer/chiller_group.py         (SLSQP 调度)           │
│   - core/safety/supervisor.py               (8 条硬规则最终闸门)    │
│   - services/control_service.py             (装配点)               │
└──────────────────────────────────────────────────────────────────┘
                              │ BACnet / Modbus / MQTT
┌──────────────────────────────────────────────────────────────────┐
│ DDC / BAS                                                         │
│   - adapters/bacnet/base.py                                       │
│   - adapters/modbus/base.py                                       │
│   - adapters/mqtt/base.py                                         │
│   (执行命令、回采点位、本地连锁保护)                                  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ LLM (运维 Copilot ONLY)                                            │
│   - services/reporting_service.py                                 │
│   - core/reporting/llm_client.py::LLMClient.summarize             │
│   - core/reporting/report_agent.py                                │
│   严禁调用控制链；只读 HistoryLogger，输出自然语言摘要。              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 8. 新系统定位

> **基于负荷预测与非线性优化的冷站群控节能平台。**

显式声明：

- 不再宣传为 "AI 全能智慧建筑平台"。
- LLM **不参与控制链**；LLM 只允许出现在 `services/reporting_service.py` + `core/reporting/` 的运维报告路径中。
- 平台的工业属性来自三件事：本地真实负荷预测 (sklearn) + SLSQP 非线性优化 + `SafetySupervisor` 终端硬闸门。

---

## 9. 下一步开发顺序

按优先级递减排列的路线图：

1. **真实 BACnet / Modbus / MQTT 驱动落地**：将 `adapters/<protocol>/base.py` 的接口骨架接到 `bacpypes3` / `pymodbus` / `paho-mqtt` 等库，完成现场点位读写。
2. **用现场历史 CSV 替换合成数据集**：`train/datasets/` 当前训练样本是合成的；接入 `data/history/history_log.csv` 经清洗后的真实采样。
3. **预测器从 Ridge 升级**：等特征工程更丰富 (天气预报、占用率、节假日) 后切换到 LightGBM / XGBoost；接口层 `prediction/load_forecast_service.py` 已为可替换设计。
4. **把 `predicted_next_load_kw` 接入决策层**：当前 (v1 review 第 1 条) 预测结果写到 `engine_state['predicted_next_load_kw']` 但仅供观测；下一步把它喂到 `MPCStrategy._price_at` 周围的代价模型 (作为下一步负荷估计的来源)，或在 `RuleBasedStrategy` 的阈值判断中作为 trailing average 的延展。
5. **新增 Pyomo MILP 备选机组组合**：在 `core/optimizer/` 下增加 `chiller_group_milp.py`，与 SLSQP 形成可切换的双解法。
6. **水力模型扩展**：`HydraulicNetworkModel` 当前用简化的速度平方损耗近似，下一步引入分支管段、止回阀、平衡阀的非线性曲线。
7. **EnergyPlus FMU 集成测试**：在 `tests/` 下建立 EnergyPlus FMU 黑盒回归用例，验证全平台跨季节工况稳定性。
8. **每区占用率排程学习**：把楼宇逐区域占用率预测做成在线学习子模块，喂给 `LowSensorMode` 与 MPC。
9. **CHW 供水温度设定值优化**：当前固定 7℃；纳入优化变量后 (受 `SafetySupervisor` 范围约束)，可获得额外节能空间。
10. **变压器保护优先级队列**：当总负荷接近变压器额定时，按重要性排序自动卸荷的优先级队列。
11. **UI 模块进一步拆分**：把 `ui/dashboard/main_window.py` 拆分为 `ui/charts/` (图表组件) 与 `ui/controls/` (控件组件) 两个子包，目录已预留。

---

## 10. 哪些代码必须优先重构

下一轮重构的硬骨头，按优先级递减：

1. **`core/physics/hydraulic.py::HydraulicNetworkModel`**：当前对二次环路拓扑做了若干隐式假设 (单一总管 + 等阻抗支管)，工程现场拓扑通常更复杂；需将拓扑改为显式数据驱动 (节点 + 边 + 设备字典)。
2. **`core/physics/simulation_engine.py::PhysicsSimulationEngine`**：单文件 ~430 行，仍涵盖空气侧 + 水侧 + 蓄冷 + 末端联动多个域；下一步按物理域再拆为 `airside.py` / `waterside.py` / `storage.py`。
3. **`core/config.py::ConfigManager`**：当前校验是松散的字典访问 + 容错回退；建议引入 `pydantic v2` 模型给所有 `sys_config` / `building_config` / `scenario` 强类型 schema。
4. **`ui/dashboard/main_window.py`**：当前仍有 711 行 (legacy 中是 1655 行的部分)，下一轮按 `FEAT-NEXT` 拆为：仪表板骨架 (`main_window.py`) + 图表组件 (`ui/charts/*`) + 控件组件 (`ui/controls/*`)；目录骨架已就位。

---

*以上为重构后的固化文档。任何后续变更必须保持 "LLM 不进入控制链" 这一红线；触发该红线的 PR 由 `tests/test_no_llm_in_control.py` / `test_no_llm_in_control_v2.py` 自动拦截。*
