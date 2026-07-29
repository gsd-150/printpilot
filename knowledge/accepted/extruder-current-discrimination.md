---
id: extruder-current-discrimination
title: 用挤出机电流方向区分机械堵塞与参数性欠挤出
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [clog, under-extrusion, extruder, discrimination]
---

流量不足只说明有东西没出来，不说明为什么。原因要看挤出机电流的**变化方向**。

机械通路变窄时，推送同样多的料需要更大的力，因此**电流随流量下降而上升**。
而 flow 设定偏低只是少推料，通路并未改变，阻力不变——推的料少了，
所需推力本就**略小**。

两者因此耦合方向相反：

| 机制 | 流量 | 电流 |
|---|---|---|
| 机械性堵塞 | ↓ | **↑** |
| 参数性欠挤出 | ↓ | 持平或**略降** |

符号差异比绝对阈值稳健，且不随机型与材料漂移——绝对值会随挤出机型号、
齿轮比、料丝直径变化，符号不会。

**电流正常而流量偏低，不是堵塞。** 机械受阻必然伴随推力上升；
没有推力上升就没有机械阻力。这是最容易被忽略、也是误判代价最高的一条。
