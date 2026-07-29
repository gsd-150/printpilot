---
id: underextrusion-parameter-signature
title: 参数性欠挤出的信号特征
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [under-extrusion, flow, signature]
---

参数性欠挤出是一个**设定**，不是一次**事件**。

因此它与所有堵塞类故障有一个时序上的硬区别：**从第一层就存在**，
没有起始点、没有过渡段、也不随打印进程恶化。堵塞有起始层，它没有。

典型特征组合：

- 流量比全程近似恒定，略低于 1.0
- 挤出机电流正常或略低于标称——推的料少，所需推力略小
- 温度正常

如果观察到的流量亏损**从第一层就存在且幅度不变**，机械堵塞的可能性很低：
通路不会在打印开始前就恰好窄到一个恒定值。

处置是提高 flow 百分比。它直接缩放指令挤出量，因此是这一类故障中
少数可以通过参数真正修复的。
