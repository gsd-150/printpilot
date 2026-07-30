---
id: loop-demo-normal-suspicious-75a04c25
title: 流量尾部均值偏低无干预通过
source_title: 闭环复盘：案例 demo-NORMAL_SUSPICIOUS（合成）
source_url: ''
license: CC-BY-4.0（本项目合成案例复盘）
retrieved_at: '2026-07-30'
applicable_material:
- PLA
evidence_level: case_history
tags:
- flow_tail
- suspicious
- no_action
- gate_allow
---

现象：flow_tail_mean为0.9657（标称下限0.985），其他流量与温度特征均在正常范围。判断与动作：系统诊断为NORMAL_SUSPICIOUS（置信度0.75），理由为流量凹陷已恢复且无持续偏差，干预风险高于收益，故采取无干预。门禁裁决：安全门禁允许通过。测得结果：打印前质量评分0.893，未记录干预后数据。局限：本案例仅单个特征轻微越限，未验证类似情况下的其他诊断或干预结果。
