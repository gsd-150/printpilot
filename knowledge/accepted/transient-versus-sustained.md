---
id: transient-versus-sustained
title: 瞬时扰动与持续性故障的区分
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [false-positive, normal, duration]
---

换料、几何切换、启动瞬态都会造成流量短暂下探。**这些不是故障。**

它们与轻度堵塞的**深度可以相当**——都可能掉到 0.8 附近。区别不在深度，
在**是否恢复**：

| | 瞬时扰动 | 持续性故障 |
|---|---|---|
| 最低点 | 可以很低 | 可以不低 |
| 恢复 | 数层内回到正常 | 不恢复 |
| 尾段占比 | 低 | 高 |

**判据是持续时间占比，不是最低点。** 只看 `flow_min` 会把每一次换料都报成堵塞。

正确响应是**不动作**。对一次已经恢复的扰动做参数干预，是在给一个不存在的问题
施加一个真实的变更——净期望为负。

一个观测边界：若下探发生在打印末段，恢复过程不在数据里，此时它与堵塞起始
在物理上不可区分，应当弃权而非猜测。
