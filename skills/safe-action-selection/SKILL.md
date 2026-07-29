---
name: safe-action-selection
description: >
  在已有根因假设后使用，把根因映射为动作类型。当 flow_tail_mean 或 current_delta
  指向机械性故障时尤其关键：此类故障禁止走参数补偿路径。本技能给出各故障允许的动作、
  明令禁止的动作，以及置信度不足时的升级规则。
version: 0.1.0
domain: fdm/decision
required_inputs:
  - flow_tail_mean
optional_inputs:
  - current_delta
  - temp_deviation_tail
triggers:
  - flow_tail_mean
  - current_delta
  - temp_deviation_tail
missing_input_policy: degrade_with_lower_confidence
minimum_evidence_count: 1
tags: [safety, action, remediation]
---

# 安全动作选择

## 原则

**诊断的代价是不对称的，动作的代价更不对称。**

把参数问题误判为堵塞，代价是一次多余的停机——浪费时间。
把堵塞误判为参数问题，代价是**向受阻的喷嘴增大流量**：挤出压力进一步上升、
驱动齿轮磨削料丝、热端积料。一个可修的故障因此变成一次拆机。

所以动作不是「参数补丁」一种。

## 映射表

| 根因 | 允许的动作 | 禁止的动作 |
|---|---|---|
| `CLOG_FULL` | `ABORT_PRINT`、`MAINTENANCE_REQUIRED` | **任何参数补丁** |
| `CLOG_PARTIAL` | `PAUSE_AND_INSPECT`、`MAINTENANCE_REQUIRED` | **提高 flow 或速度** |
| `UNDEREXT_PARAM` | `APPLY_PARAM_PATCH` | — |
| `THERMAL_DRIFT` | `APPLY_PARAM_PATCH` | — |
| `NORMAL_SUSPICIOUS` | 不动作 | 任何干预 |
| `UNKNOWN` | `ESCALATE_TO_HUMAN` | 任何自动动作 |

## 为什么堵塞不能靠调参"修复"

恢复流动需要的是物理干预：加热软化后抽出料丝（cold pull）、清理喷嘴、必要时拆检。
继续打印并提高流量，**只会把堵塞推向更严重的状态**。

部分堵塞允许保守降速等临时缓解，但必须先暂停检查——缓解不等于修复。

## 排除项

- **「电流略低」不构成排除完全堵塞的理由。** 驱动打滑后负载反而下降；
  低电流可能意味着它已经完全没在推料。
- **不要因为流量数值处于"中等"就默认可调参。** 决定动作类型的是根因类别，
  不是偏离幅度。
- **置信度不足时不要退而求其次选一个"比较安全"的参数动作。**
  任何参数动作都预设了"机械通路正常"，而这正是不确定的部分。应当升级至人工。
- **多个故障并存时取最严格的动作。** 若堵塞的可能性无法排除，即使参数问题
  的置信度更高，也不得下发参数补丁。

## 与硬约束的关系

本技能是**建议**，不是许可。所有动作仍须经 `SafetyGate` 的硬规则校验：
硬件安全边界、单位合法性、越界拒绝。本技能与硬规则冲突时，**以硬规则为准**。

优先级链：硬件安全规则 > 经审核的 Skill > 有来源的 RAG 证据 > 模型自身知识。
