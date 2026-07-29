---
id: clog-full-signature
title: 完全堵塞的信号特征
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [clog, extruder, signature]
---

完全堵塞时流量比在两三层内塌陷至接近零，**此时流量读数本身已经决定性**，
不需要电流佐证。

电流的走势有一个容易误读的形态：

1. 堵塞发生瞬间，驱动齿轮顶住阻力，电流**尖峰**
2. 齿轮开始打滑、磨削料丝之后，负载反而**下降**到低于正常水平

因此「电流偏低」不构成排除完全堵塞的理由——它可能意味着驱动已经**完全没在推料**。
只看电流均值而不看时序形态，会把完全堵塞读成正常。

流量塌陷时，任何参数补偿都无从生效：通路已经不通，提高 flow 只是让齿轮
磨得更快。
