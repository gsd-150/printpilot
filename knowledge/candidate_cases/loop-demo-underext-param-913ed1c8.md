---
id: loop-demo-underext-param-913ed1c8
title: 欠挤出补偿打印质量提升
source_title: 闭环复盘：案例 demo-UNDEREXT_PARAM（合成）
source_url: ''
license: CC-BY-4.0（本项目合成案例复盘）
retrieved_at: '2026-07-30'
applicable_material:
- PLA
evidence_level: case_history
tags:
- underextrusion
- param-patch
- flow
- quality
---

现象：flow_tail_mean为0.8753（标称下限0.985），flow_deficit_fraction和flow_tail_deficit_fraction均为1.0（标称上限分别为0.35和0.32），表明绝大部分层存在流量不足；电流、电流波动、温度偏差等指标在标称范围内。
判断与动作：系统诊断为UNDEREXT_PARAM（欠挤出参数），置信度0.80；动作apply_param_patch（风险中等），理由为“挤出量持续偏低而机械阻力正常，小幅提高flow补偿”，补丁为流量增加5%。
门禁裁决：安全门禁允许执行。
测得结果：打印质量评分从0.634提高到0.744（提升0.110），结果改善。
局限：基于仿真数据，仅反映本次案例；未涉及其他潜在因素。
