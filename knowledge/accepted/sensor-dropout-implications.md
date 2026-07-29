---
id: sensor-dropout-implications
title: 传感器缺失时的判断边界
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0（本项目原创内容）
retrieved_at: 2026-07-30
applicable_material: [PLA, PETG, ABS, TPU]
evidence_level: first_principles
tags: [abstention, sensor, missing-data]
---

**一个算不出的特征不是一个正常读数。** 它是没有被测量。

把缺失当作正常，等于在没有证据的方向上作出了一个断言。这两种状态必须在
数据结构里就可区分，而不是同时表现为"没有告警"。

具体到挤出异常：失去挤出机电流后，机械堵塞与参数性欠挤出**不可区分**。
两者的流量曲线本就重叠，电流是唯一的判别依据。此时：

- 正确答案是弃权，并指明缺少哪项测量
- 不正确的做法是选择先验概率更高的那一类——两者处置相反，
  猜测的期望代价为负而非零

例外：流量已经塌陷至近零时，流量读数本身已经决定性，不需要电流。
此时弃权是过度保守。

弃权不是失败，是在证据不足时给出的正确输出。
