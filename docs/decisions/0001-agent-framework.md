# ADR 0001 — 采用 LangGraph 作为编排框架

- **状态**：已接受
- **日期**：2026-07-29
- **里程碑**：M2
- **验证版本**：`langgraph 1.2.10` / `langchain-core 1.5.2` / `pydantic 2.13.4` / CPython 3.12.13

---

## 背景

规划 v1 打算自研编排器（`orchestrator.py`）。自研能说明对控制流的理解，但它证明不了岗位要求里的一条：**"了解至少一种 AI Agent 开发框架，有跑通 Demo 或课程项目经验者优先"**。评审报告 P0-2 指出了这个缺口。

同时本项目对编排层有三个硬需求：

1. **状态必须是可校验的结构**，不能是自然语言累积——这是"节点间传契约不传散文"这一主张的前提。
2. **确定性节点与 LLM 节点混在同一张图里**。感知和执行是纯 Python，诊断和决策才调模型。
3. **条件边**，用于安全门禁的放行/拦截/人工升级分支，以及降级重试。

## 决策

采用 **LangGraph 的 `StateGraph`**，版本约束 `>=1.2,<2`。

不使用 prebuilt 的 ReAct agent。本项目主干是固定顺序，用预置 agent 反而要绕开它的循环逻辑。

## 实测验证

不凭文档假设，直接对目标版本探测。以下均为实际运行结果：

| 探测项 | 结果 | 对本项目的意义 |
|---|---|---|
| Pydantic `BaseModel` 作为 state schema | ✅ 支持 | 需求 1 满足 |
| 确定性函数与调用 LLM 的函数混用为节点 | ✅ 支持 | 需求 2 满足 |
| `add_conditional_edges` + `path_map` 分支 | ✅ 支持 | 需求 3 满足 |
| `invoke()` 的返回类型 | ⚠️ 返回 **`dict`**，不是 state 模型实例 | 下游不能假设属性访问，需显式转回模型 |
| 节点返回**未知字段** | ⚠️ 静默**丢弃**，不报错 | 拼错字段名不会有任何提示 |
| 节点返回**错误类型** | 🔴 **静默接受** | `flow_ratio: float` 被写入字符串后 state 仍然"合法"通过 |
| 节点返回 `None` | ✅ 视为空操作 | 可用于只读节点 |

### 关键发现：state schema 只在入口校验，不在节点写回时校验

```python
class MiniState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow_ratio: float = 1.0

# 节点返回错误类型
graph.add_node("n", lambda s: {"flow_ratio": "not-a-number"})
# → 不报错。最终 state: {'flow_ratio': 'not-a-number'}
```

这对本项目是实质问题。整个架构论点是"节点之间传递经校验的结构化数据，而不是自然语言"，而框架只保证了**形状**，没保证**取值合法**。如果诊断节点因为一处 bug 把置信度写成字符串，安全门禁读到的就是一个类型错误的值，而这恰恰是最不该出错的地方。

### 应对

新增 `printpilot.workflow.validating_node`：把节点的返回值合并到当前 state 后用 schema 重新校验，不合法则抛 `NodeContractError`。约 20 行，所有节点统一包一层。

违规时**立刻抛错而不降级**——这是我们自己节点的 bug，不是需要容错的运行时状况。降级路径留给 LLM 超时/限流那类外部故障。

`tests/test_langgraph_smoke.py` 同时钉住了两件事：包装器能拦住错误类型和未知字段；以及**未包装时框架确实会放行**。后者是为了在将来升级 LangGraph 时，如果官方补上了这个校验，测试会失败并提醒我们移除自己的包装层。

## 后果

**正面**
- 满足岗位对框架经验的要求，且能解释清楚 workflow 与 agent 的区别
- 条件边、checkpoint 回放、状态通道都是现成的，自研要花不少时间
- 强制先把状态结构想清楚，这对 M4 是好事

**负面 / 代价**
- 依赖树显著变大（langgraph 带入 langchain-core、orjson、httpx 等十余个包），而本项目只用其中一小部分
- 需要自己补节点写回校验，框架不提供
- API 跨大版本有变动历史，因此上限锁到 `<2`，升级时必须重跑 smoke test

**明确不采用的**
- prebuilt ReAct agent：主干是固定顺序，用它需要绕开其循环逻辑
- LangChain 的 chain 抽象：本项目不需要，直接用 `StateGraph` 更清楚

## 命名上的诚实性

LangGraph 官方文档区分：**预定路径的叫 workflow，能动态决定工具和步骤的才叫 agent**。

按这个标准，PrintPilot 是 **3 个 LLM Agent 节点 + 3 个确定性节点组成的混合式 agentic workflow**，不是"5 个 Agent 的多智能体系统"。主干顺序固定，只在重试、降级、安全升级处有条件边。

对外一律用前一种说法。把每个 Python 函数都叫 Agent 经不起追问。
