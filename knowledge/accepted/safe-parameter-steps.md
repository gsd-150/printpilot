---
id: safe-parameter-steps
title: 参数调整的安全步长与回滚
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: community_practice
tags: [parameter, safety, rollback]
---

单次调整应当**小**。一个能一步修好问题的补丁，在诊断错误时也会一步把问题弄坏。

保守步长参考：

| 参数 | 单步 | 理由 |
|---|---|---|
| flow | ±5% | 更大的跳变会掩盖原始故障的走势 |
| 热端温度 | ±5–10℃ | 热端有惯性，过大调整会过冲 |
| 打印速度 | ±10% | 影响挤出压力与层间结合 |

每次调整都应当能被**精确回滚**。回滚值应记录调整前的实际读数，
而不是用调整量反减——若调整量被边界截断，反减得到的不是原值。

调整后需观察足够多的层再判断效果。热端温度尤其如此：
温度变化到影响挤出量之间存在滞后。
