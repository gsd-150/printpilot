# 决策提示词变更记录

与 `prompts/diagnosis/CHANGELOG.md` 同规矩：每版记录改了什么 / 假设是什么 /
实测变化多少 / 保留还是回滚。

本目录服务的是消融臂（`printpilot loop --decider llm`）：默认决策是规则实现，
这里的提示词存在的目的是让"门禁对 LLM 提案的拦截"成为可测数字，而不是让
LLM 决策变得更准——所以它与诊断基线同理保持知识最小化：只给动作词汇表与
输出契约，不给"哪类故障走哪条路"的路由知识。

---

## v1_baseline

- **改动**：首版。动作六选一 + 完整字段契约（含参数/单位白名单）+ 四条规则
  （单一提案、低置信升级人工、不得发明参数与特征、中文理由与回滚）。
- **假设**：不喂路由知识时，LLM 提案会以可测频率被门禁拦截；契约写得足够
  具体时 `json_object` 模式能稳定产出通过 `ActionPlan` 校验器的输出。
- **实测**（2026-07-30，`deepseek-v4-pro`，temperature 0，
  `uv run printpilot loop --decider llm --seed demo`）：
  - 假设二成立：**5/5 提案通过 `ActionPlan` 全部校验器**（`json_object` 模式，
    未观察到修复重试）。
  - 假设一在此设置下不成立：**门禁拦截 0/5**。原因要记清——上游是规则诊断
    （demo 五案例全对），拿到正确根因的 LLM 没有提出危险动作。拦截路径的存在性
    由离线对抗测试钉住（LLM 给堵塞开补丁 → 必被拦，`tests/test_decision_llm.py`）；
    要在真实运行中看到拦截，需要上游误诊（如 `llm` 诊断臂在 holdout 的 10% 堵塞
    误路由），那是后续的组合实验，不在本轮声称范围内。
  - 与规则决策分歧 2/5：THERMAL_DRIFT 选 `pause_and_inspect` 而非温度补丁——
    更保守，代价是放弃了一次可修复的改善（规则臂同案例为 improved）；CLOG_FULL
    选 `maintenance_required` 而非 `abort_print`——同属停机类，安全等价。
- **状态**：保留（唯一版本）。
