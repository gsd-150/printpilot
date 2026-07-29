# PrintPilot

**FDM 打印过程异常诊断与安全动作决策系统**

从打印过程遥测中识别挤出异常，区分**可调参修复**与**必须停机维护**两类根因，并在硬安全门禁下给出可审计、可回滚的动作计划。

---

## ⚠️ 边界声明

请先读这一段，再看下面任何内容。

| | |
|---|---|
| **数据** | 全部为**合成遥测**，由本仓库的仿真器生成。不是真实产线数据。 |
| **传感器** | `flow_ratio`、`extruder_current` 等均为**虚拟传感器**。普通消费级 FDM 设备未必直接提供这些信号。 |
| **硬件** | **不连接、不控制任何真实打印机。** 系统输出的是*建议动作*，不是设备指令。 |
| **仿真保真度** | 未经实机标定。本项目**不使用"数字孪生"这一表述**——它意味着与真实资产的双向同步和保真度标定，二者本项目都没有。 |
| **可检测范围** | 只诊断**过程异常与缺陷风险**。翘曲、拉丝、层间结合弱等外观/力学缺陷需要视觉或成品检测才能确认，不在本项目声称范围内。 |

所有指标均来自合成数据，存在上界。任何数字都可由 `datasets/manifest.json` 中记录的种子与场景版本复现。

---

## 当前完成度

**5 / 8 里程碑已验证**（由 `printpilot info` 在运行时报告，非手工维护）

| | 里程碑 | 验收标准 |
|---|---|---|
| ✅ | **M1** 工程骨架、schemas、CI、离线 mock LLM | `ruff` + `mypy` + `pytest` 全绿 |
| ✅ | **M2** LangGraph 选型验证与节点契约校验 | [ADR 0001](docs/decisions/0001-agent-framework.md) + `tests/test_langgraph_smoke.py` |
| ✅ | **M3** 合成遥测环境：故障注入 + 虚拟传感器 + 独立质量评估器 | `printpilot dataset` 产出 160 条 + manifest |
| ✅ | **M4** 感知层 + 规则基线 + 评测体系 + LLM 诊断节点 | `printpilot eval --split dev` 输出基线指标 |
| ✅ | **M5** 2 个 Skill + 注册机制 + 接入诊断，dev 消融完成 | `printpilot skills validate` 能拦住坏 Skill |
| ⬜ | M6 单向量后端 + 知识卡 + 检索评测 | Hit@k / MRR 为实测值 |
| ⬜ | M7 Decision + SafetyGate + Execution + 一轮闭环 | `test_safety_gate.py` 全绿 |
| ⬜ | M8 消融、Trace、Demo | 五档消融表填满实测值 |

### 消融结果（dev n=100 / holdout n=30，实测）

| 配置 | dev | holdout | **堵塞误入参数路径** dev / holdout | token/案例 |
|---|---|---|---|---:|
| rules-only | **0.960** | **0.933** | **0.000 / 0.000** | 0 |
| llm | 0.510 | 0.400 | 0.000 / 0.000 | 3,811 |
| llm + Skills | 0.710 | 0.667 | 0.010 / **0.100** | 6,721 |

**规则基线严格支配，没有一条反例。** 配对检验（McNemar 精确）显示：两个划分上 LLM 都**没有答对过任何一条规则基线答错的案例**（dev 25:0，holdout 8:0）。这比准确率差距更强——它意味着 LLM 在本任务上不提供任何互补覆盖。

任务的判别依据就是少数几个连续特征的阈值与符号，这类判断可以被精确写下来；交给概率系统只是把确定性换成不确定性，还附带成本和延迟。**这正是本项目把感知层与执行层留在 Python 的理由。**

**Skills 确实有效，并在 holdout 上复现**（p=0.0078，8:0 无反例）：`UNDEREXT_PARAM` 由 20/20 全错降到 2 错。修复发生在定性诊断预测的位置——模型缺的是"电流正常即无机械阻力"这条事实，而不是推理纪律。

**最严重的发现**：`llm+skills` 在 holdout 上把 **10% 的堵塞送进了参数路径**。在真实设备上这意味着向受阻的喷嘴增大流量。这直接验证了 SafetyGate（M7）的必要性——模型不能被信任来路由堵塞，动作层必须有纯 Python 的硬拦截。

完整分析见 [ablation.md](evals/results/ablation.md)。**challenge 划分的 LLM 档尚未运行**，且合成数据使全部指标存在上界——本报告不支持"LLM 在此类任务上总是更差"这一更强的结论。

---

## 快速开始

需要 Python 3.12 或 3.13。推荐用 [uv](https://docs.astral.sh/uv/)：

```bash
uv venv --python 3.12
```

```bash
uv pip install -e ".[dev]"
```

```bash
uv run printpilot info
```

未安装 uv 时，等价命令为 `py -3.12 -m venv .venv`、`.venv\Scripts\pip install -e ".[dev]"`、`.venv\Scripts\printpilot info`。

**本项目不使用 Makefile 作为复现路径**——目标环境是 Windows，默认没有 GNU Make。上述命令跨平台可用。

### 运行检查

```bash
uv run ruff check . ; uv run mypy ; uv run pytest
```

核心测试**不需要 API key**，全部通过 `MockLLMClient` 离线运行。

---

## 设计要点

### 这不是"5 个 Agent"

准确说法是 **3 个 LLM Agent 节点 + 3 个确定性节点组成的混合式 agentic workflow**。LangGraph 官方文档区分 workflow 与 agent：预定路径属前者，能动态决定工具和步骤才是后者。本项目主干是固定顺序，仅在重试/降级/升级处有条件边。把每个 Python 函数都叫 Agent 并不诚实。

| 节点 | 类型 | 说明 |
|---|---|---|
| Perception | 纯 Python | 特征提取。确定性任务不调用 LLM。 |
| Diagnosis | LLM Agent | 带证据与引用；**允许输出 `UNKNOWN`** |
| Decision | LLM Agent | 产出 `ActionPlan`，**只能提议** |
| SafetyGate | 纯 Python | 硬约束裁决。LLM 不可绕过。 |
| Execution | 纯 Python | 写配置、留 diff、可回滚 |
| Reflection | LLM Agent | 只写候选隔离区，不直接入知识库 |

### 核心任务是一个代价不对称的判断

`CLOG_PARTIAL`（部分堵塞）与 `UNDEREXT_PARAM`（参数性欠挤出）在流量比曲线上很相似，但处置相反：

- 把参数问题误判为堵塞 → 浪费一次停机
- 把堵塞误判为参数问题 → **向受阻的喷嘴增大流量**，抬高挤出压力、加剧挤出机磨料

因此决策输出不是参数补丁，而是含 `PAUSE_AND_INSPECT` / `MAINTENANCE_REQUIRED` / `ABORT_PRINT` / `ESCALATE_TO_HUMAN` 的五类动作，并由 `SafetyGate` 硬规则保证完全堵塞永远不会被自动调参继续打印。

### 数据集的难度是设计出来的，不是碰巧的

仿真器第一版把两类故障的残余流量设成了 0.62–0.84 与 0.86–0.95——**区间不重叠**，一条 0.84 的阈值就能完美分开。那样的基准测的是阈值，不是诊断。

现在两者是重叠的，`tests/test_simulator.py::TestDifficulty` 把这个性质钉死：

| 故障 | 尾段 flow_ratio | 尾段 extruder_current |
|---|---|---|
| `CLOG_PARTIAL` | 0.730 – **0.918** | 0.387 – 0.517 ↑ |
| `UNDEREXT_PARAM` | **0.798** – 0.931 | 0.340 – 0.350 ↓ |

在 0.798–0.918 这段流量曲线上两者无法区分，只能靠电流**耦合方向**判断：机械受阻使推料力上升，而 flow 设定偏低只是少挤，推力反而略降。

数据集还包含三类难例：`NORMAL_SUSPICIOUS` 的瞬时凹陷深度与轻度堵塞相当（须看持续时间而非深度）；challenge 集里有未见过的材料、超范围噪声；以及 10 条**移除了 `extruder_current`** 的案例——失去判别信号后，正确答案是 `UNKNOWN`，而不是猜一个。

### 知识冲突优先级

### 框架只保证形状，不保证取值

实测 langgraph 1.2.10：Pydantic state schema **只在 `invoke()` 入口校验，节点写回时不校验**。节点返回未知字段会被静默丢弃；返回**错误类型**会被静默接受——`flow_ratio: float` 里可以躺着一个字符串。

本项目主张"节点之间传经校验的结构，而不是散文"，这个缺口正好戳在主张上。因此所有节点统一经 `validating_node` 包装，把更新合并回 state 后重新校验，违规抛 `NodeContractError`。测试同时钉住了"未包装时框架确实放行"，以便将来官方补上校验时能被发现。

详见 [ADR 0001](docs/decisions/0001-agent-framework.md)。

### 安全指标不能单独解读

「堵塞误入参数路径率」是本项目最关心的失效模式，目标为 0。但它有一个退化解：

> **一个把所有案例都判成"堵塞"的系统，这项指标天然满分。**

这不是假想。LLM 基线 v1 在 20 条样本上判了 15 次 `CLOG_PARTIAL`，准确率只有 0.450，而安全指标恰好是 0.000——正因为堵塞被过度预测，它自然永远不会被送进参数路径。

所以评测报告中安全指标始终与准确率、弃权率并排呈现，不单独引用。

### 知识冲突优先级

> 硬件安全规则 > 经审核的 Skill > 有来源的 RAG 证据 > LLM 自身知识

被覆盖的低优先级来源记入 trace，不静默丢弃。

---

## 项目结构

```text
src/printpilot/
├── domain/          参数、故障目录、节点间契约
├── llm/             LLM 边界 + 离线 mock
├── simulator/       合成遥测与故障注入          (M3)
├── workflow/        节点契约校验；StateGraph     (M4)
├── skills_runtime/  Skills 注册、校验、路由      (M5)
├── rag/             知识库构建、清洗、检索        (M6)
├── harness/         trace / 降级 / 成本           (M7)
└── eval/            数据集切分、指标、消融        (M4+)
```

设计文档见 [项目规划_v2.md](项目规划_v2.md)（v1 保留作为修订对照）。

---

## 许可

MIT，见 [LICENSE](LICENSE)。知识卡片内容基于公开工艺资料自行撰写并注明来源，不整篇转载他人文档。
