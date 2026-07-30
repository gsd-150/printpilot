---
id: loop-demo-clog-full-b3728ca2
title: CLOG_FULL诊断触发停机
source_title: 闭环复盘：案例 demo-CLOG_FULL（合成）
source_url: ''
license: CC-BY-4.0（本项目合成案例复盘）
retrieved_at: '2026-07-30'
applicable_material:
- PLA
evidence_level: case_history
tags:
- clog
- flow
- abort
- gate
---

现象：
该轮次PLA打印中，流量相关指标均严重偏离正常范围：flow_tail_mean=0.0828（正常界值>0.985），flow_min=0.0788（正常界值>0.7），flow_deficit_fraction=0.5（正常界值<0.35），flow_tail_deficit_fraction=1.0（正常界值<0.32）。同时，电机电流低于正常：current_mean=0.2981A（正常界值>0.345），current_delta=-0.1985A（正常界值>-0.012）。温度偏差指标在正常范围内。

判断与动作：
系统诊断为CLOG_FULL（置信度0.95），提出高风险动作abort_print。理由：流量比骤降至近0，无法通过参数补偿继续打印，需停机并进入恢复流动/cold pull/拆检流程。

门禁裁决：
安全门禁允许执行该动作。

测得结果：
打印前质量得分0.188（较低）。因系统中止打印，未获得打印后质量得分。

局限：
本案例为单次合成演示数据，未经历恢复流程，结论仅限于该轮次表现。
