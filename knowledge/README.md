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
