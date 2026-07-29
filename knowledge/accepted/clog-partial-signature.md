---
id: clog-partial-signature
title: 部分堵塞的信号特征
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [clog, extruder, signature]
---

部分堵塞是**渐进**的：通路逐步变窄，流量在若干层内缓慢下滑并稳定在一个残余水平，
而非骤降。

典型特征组合：

- 流量比在起始层之后缓降，随后维持在一个低于正常但明显大于零的水平
- 挤出机电流随流量下降而**同步上升**——通路变窄，推料需要更大的力
- 温度与加热占空比通常正常，除非堵塞已导致热端热量传导异常

与完全堵塞的区别在于**速率与终值**：部分堵塞在数层内完成过渡且仍有出料，
完全堵塞在两三层内塌陷至近零。

与参数性欠挤出的区别**不在流量幅度**，两者的残余流量区间高度重叠。
判别依据是电流方向，见 `extruder-current-discrimination`。
