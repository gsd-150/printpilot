---
id: moisture-induced-underextrusion
title: 受潮料丝造成的间歇性欠挤出
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PETG, ABS, TPU, PLA]
evidence_level: community_practice
tags: [moisture, under-extrusion, false-positive]
---

吸湿材料（PETG、ABS、TPU 尤为明显）在熔融时，料丝内的水分汽化形成气泡，
造成**间歇性**挤出不足，并常伴有爆鸣声。

它的波形可以伪装成渐进堵塞：流量整体偏低、波动增大。但机理不同，
处置也不同——需要烘干料丝，而不是清理喷嘴或提高 flow。

区分线索：

- 受潮造成的亏损**波动大**，堵塞造成的亏损相对平稳
- 受潮不伴随挤出机电流的持续上升——通路没有变窄
- 若有湿度读数且偏高，应当降低堵塞的置信度

这是一个典型的**排除项**：它不改变主判断的方向，但会降低置信度，
并在两个候选接近时改变结论。
