---
id: loop-demo-clog-partial-7807d162
title: CLOG_PARTIAL 诊断后未执行暂停检查
source_title: 闭环复盘：案例 demo-CLOG_PARTIAL（合成）
source_url: ''
license: CC-BY-4.0（本项目合成案例复盘）
retrieved_at: '2026-07-30'
applicable_material:
- PLA
evidence_level: case_history
tags:
- clog
- flow
- current
- no_action
---

现象：
本次打印中，流量尾均值（flow_tail_mean）为0.9040，低于标称下限0.985；流量亏损比例（flow_deficit_fraction）为0.4833，高于上限0.35；流量尾亏损比例（flow_tail_deficit_fraction）为1.0000，高于上限0.32；平均电流（current_mean）为0.3770A，高于上限0.356；电流波动（current_delta）为0.0600A，高于上限0.008。温度相关特征在标称范围内。

判断与动作：
系统诊断为CLOG_PARTIAL（置信度0.85），提出动作pause_and_inspect（风险high）。判断理由：流量比缓降至0.6~0.85且挤出机电流上升，提高flow或速度会进一步抬高挤出压力并加剧磨料，必须先暂停检查。

门禁裁决：
安全门禁允许（gate: allow）。

测得结果：
打印前质量评分为0.826。本轮未执行动作（outcome: no_action），无打印后质量数据。

局限：
仅基于一次合成案例，未执行动作，无法评估动作效果。
