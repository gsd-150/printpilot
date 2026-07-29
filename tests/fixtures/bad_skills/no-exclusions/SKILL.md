---
name: no-exclusions
description: >
  当 flow_tail_mean 低于正常带时使用本技能判断挤出状态是否异常，并给出相应的
  处理建议与后续检查步骤。
version: 0.1.0
domain: fdm/extrusion
required_inputs: [flow_tail_mean]
triggers: [flow_tail_mean]
---

# 只有流程没有边界

本文件刻意不含说明何时不适用的章节，用于验证 R5 会拒绝它。

注意标题与正文都避免出现那三个字：第一版的负样本把它写进了标题，
于是既通过了子串检查、也通过了后来的标题正则——负样本不成立，
规则看起来是对的，其实从未被真正测试过。

## 判定流程

1. 读取 flow_tail_mean
2. 低于正常带即报告异常
