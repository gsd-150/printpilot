---
id: loop-demo-thermal-drift-7da00e42
title: 喷嘴温度下调8°C补偿热端温度漂移
source_title: 闭环复盘：案例 demo-THERMAL_DRIFT（合成）
source_url: ''
license: CC-BY-4.0（本项目合成案例复盘）
retrieved_at: '2026-07-30'
applicable_material:
- PLA
evidence_level: case_history
tags:
- thermal_drift
- flow_deficit
- compensation
- gate_allow
---

现象：
在本轮打印中，flow_tail_mean 为 0.9475（额定下限 0.985），flow_deficit_fraction 为 0.5500（上限 0.35），flow_tail_deficit_fraction 为 0.8000（上限 0.32），temp_deviation_tail 和 temp_bias_tail 均为 0.0836（上限 0.045），以上参数均超出额定范围。current_mean 和 current_delta 未超出范围。

判断与动作：
系统诊断为 THERMAL_DRIFT（置信度 0.80），提出动作 apply_param_patch（风险 medium），理由是“热端温度持续偏离设定值，调整设定以补偿偏差”，具体补丁为喷嘴温度下调 8℃。

门禁裁决：
门禁裁决为 allow。

测得结果：
动作前品质分数 0.717，动作后品质分数 0.745，提升 0.028，结果为 improved。

局限：
本结论仅基于单轮打印数据，无法推广至其他情况；品质分数来自模拟评估。
