---
id: knowledge-conflict-priority
title: 知识来源冲突时的优先级
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [governance, priority, conflict]
---

多个来源给出相互矛盾的建议时，按以下顺序裁决：

**硬件安全规则 > 经审核的 Skill > 有来源的 RAG 证据 > 模型自身知识**

理由是可问责性递减：硬件边界由设备决定且违反会造成损坏；Skill 经过人工审核
并有版本；RAG 片段有来源可追溯；模型的先验既无来源也无版本。

被覆盖的低优先级来源应当**记入 trace 而非静默丢弃**——否则事后无法解释
为什么系统没有采纳某条看似相关的建议。

一个常见误用：把"材料工艺窗口允许"当作"硬件允许"。工艺窗口是推荐值，
优先级低于硬件边界；窗口内的值仍然可能越出设备极限。
