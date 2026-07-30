# knowledge/ —— 语料与隔离区

- `accepted/`：生产知识库。`load_cards()` 与 `printpilot rag build` **只读这里**。
- `candidate_cases/`：Reflection 节点（`printpilot loop --reflect`）写入的候选
  卡片隔离区。RAG 索引读不到这里的任何内容——这由代码路径保证，不是约定。

## 审批：候选 → accepted

审批是人工动作，两步缺一不可：

1. 对照该轮闭环输出核查卡片的每一句：无外推、无编造机理、无凭空来源。
   特别地：Reflection 的输入里没有注入故障的 ground truth，任何声称知道
   "真实故障是什么"的候选卡片都应当直接拒绝——把答案写进语料再喂回诊断，
   正是 v2 修订说明第 6 条要堵住的泄漏。
2. `git mv knowledge/candidate_cases/<id>.md knowledge/accepted/`，然后运行
   `printpilot rag build` 重建索引。

候选卡片格式与 `accepted/` 完全一致（`evidence_level: case_history`，
`source_url` 恒为空），审批通过即可原样移动。拒绝 = 直接删除候选文件——
候选不是证据，`evals/runs/` 的不可删除规则不适用于这里。

## 审查记录

**2026-07-30 · 首批 5 张（`loop-demo-*`，deepseek-v4-pro 产出）**：逐卡对照轮记录
重放（`render_round`，与产卡输入同源）核查完毕——数字全部吻合，无泛化、无编造
来源、无 ground truth 声称；唯一瑕疵是 `loop-demo-clog-partial-*` 的标题
（"未执行暂停检查"易读作缺陷报告，正文表述无误）。

**结论：内容合格，全部暂缓入库，原样存档于隔离区。** 三条理由：

1. `accepted/` 的每张卡必须被检索评测集覆盖（`test_every_card_is_covered_by_at_least_one_query`
   是硬闸）——入库必须同步扩充查询集，否则 CI 失败；
2. 案例卡把本仿真器分布的精确特征值与系统诊断配对（这五例恰好全对），进入
   RAG 语料等于给未来消融提供近邻式答案键——正是数据集按场景族切分要防的
   那类泄漏的变体；
3. README 与 `evals/results/retrieval.md` 的检索指标钉在 12 卡语料上，扩容会使
   已发布数字失效。

若将来入库：先扩充查询集、重跑检索评测、并在报告中注明语料版本变更。
