---
version: 1
created: 2026-07-30
parent: none
hypothesis: 给出全轮记录与硬性诚实规则，模型能写出每句都可对照记录核查的候选卡片
result: pending
---

You are writing a post-round case note for an FDM printing diagnosis system.

Below is the complete record of one closed-loop round: the measured features of
one print, the diagnosis the system produced, the action it proposed, the
safety gate's ruling, and print quality measured before and after by an
evaluator that only sees telemetry.

## Task

Write ONE candidate knowledge card summarising what this round demonstrates.
The card goes into a quarantine folder for human review; it becomes knowledge
only if a reviewer can verify every sentence against this record. Write it to
be checkable, not to be impressive.

## Rules

1. **State only what the record shows.** No mechanism, cause or number that
   does not appear below. If the record cannot support a conclusion, write the
   weaker sentence.
2. **This is one synthetic case.** Phrase findings as what happened in this
   round, not as a general law. The quality scores come from simulation.
3. **Claim no external source.** You are not citing documentation; provenance
   is recorded by the system separately.
4. Write `title` and `body` in Chinese. Title is at most 30 characters and
   concrete — name the signal or the action, not "一次有趣的案例".
5. Structure `body` as short sections: 现象 → 判断与动作 → 门禁裁决 →
   测得结果 → 局限.
6. `tags`: 2 to 4 short lowercase English tokens, e.g. `clog`, `flow`, `gate`.

## Round record

{round}
