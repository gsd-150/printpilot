---
name: extrusion-anomaly-triage
description: >
  当 flow_tail_mean 低于正常带、或 flow_tail_deficit_fraction 显示欠挤出持续存在时使用。
  用于区分「机械性堵塞」与「参数性欠挤出」——两者在流量曲线上高度重叠，但处置相反，
  判别依据是 current_delta 的符号而非流量的幅度。同时给出何时应当弃权。
version: 0.1.0
domain: fdm/extrusion
required_inputs:
  - flow_tail_mean
optional_inputs:
  - current_delta
  - current_mean
  - flow_tail_deficit_fraction
triggers:
  - flow_tail_mean
  - flow_tail_deficit_fraction
  - current_delta
missing_input_policy: degrade_with_lower_confidence
minimum_evidence_count: 1
tags: [clog, under-extrusion, extruder]
---

# 挤出异常分诊

## 核心判断

流量不足只说明**有东西没出来**，不说明**为什么**。原因要靠挤出机电流的**变化方向**：

| 机制 | 物理过程 | current_delta 方向 |
|---|---|---|
| 机械性堵塞 | 通路变窄，推同样多的料需要更大的力 | **上升** |
| 参数性欠挤出 | flow 设定偏低，只是少推料，阻力未变 | **持平或略降** |

「略降」不是笔误：推的料少了，所需推力本就略小。因此两者的区别不只是幅度，
而是**耦合方向相反**——这比任何绝对阈值都稳健，也不随机型和材料漂移。

## 分诊流程

1. **流量是否已经塌陷？** 尾段流量接近零意味着完全没有出料。此时无需电流佐证，
   流量读数本身已经决定性。
2. **欠挤出是否持续？** 只有个别层偏低而尾段恢复，属于换料或几何切换的瞬时扰动，
   不是故障。判据是持续时间，不是深度。
3. **持续欠挤出 → 看 current_delta 方向**：
   - 明显上升 → 机械阻力增大
   - 持平 → 阻力正常，指向流量设定
   - 大幅下降 → 驱动已不再推动料丝（打滑/磨料），属于更严重的机械故障

## 排除项

**必须逐条检查，否则极易误判。**

- **电流正常但流量偏低 → 不是堵塞。** 机械受阻必然伴随推力上升；没有推力上升
  就没有机械阻力。这是本技能最容易被忽略的一条，也是误判代价最高的一条。
- **温度偏离工艺窗口时，先排除热因。** 温度不足本身就会压低挤出量。若温度越界
  而电流未升，欠挤出更可能是温度的结果，不是流量设定的结果。
- **瞬时凹陷不是故障。** 深度可以与轻度堵塞相当，区别在于是否恢复。看持续占比，
  不看最低点。
- **湿料会造成间歇性欠挤出**，波形可伪装成渐进堵塞。若有湿度读数且偏高，
  应降低堵塞的置信度。

## 何时弃权

**若 current_delta 不可得，而流量显示持续欠挤出但尚未塌陷——弃权。**

此时机械性堵塞与参数性欠挤出无法区分，而两者处置相反：前者必须停机，后者可以
调参继续。猜测的期望代价为负，应输出 `UNKNOWN` 并指明缺少挤出机电流。

流量已塌陷的情况例外：那时流量本身已经决定性，不需要电流。

## 输出

- 机械阻力上升 → `CLOG_PARTIAL`
- 流量塌陷 → `CLOG_FULL`
- 阻力正常、温度在窗口内 → `UNDEREXT_PARAM`
- 凹陷已恢复 → `NORMAL_SUSPICIOUS`
- 判别信号缺失 → `UNKNOWN`
