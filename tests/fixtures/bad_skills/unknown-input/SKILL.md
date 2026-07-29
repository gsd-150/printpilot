---
name: unknown-input
description: >
  当 nozzle_vibration_rms 超出正常带时使用，用于判断喷头是否存在异常振动，
  并据此推断机械结构的松动情况。
version: 0.1.0
domain: fdm/mechanical
required_inputs: [nozzle_vibration_rms]
triggers: [nozzle_vibration_rms]
---

# 声明了不存在的输入

`nozzle_vibration_rms` 不是感知层会产出的特征。这个技能能通过人工评审——文字读起来
完全合理——但永远不会被路由选中，因为它等待的信号根本不存在。

## 排除项

无。本技能存在的意义是被 R3 拦下。
