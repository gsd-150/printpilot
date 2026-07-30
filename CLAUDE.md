# PrintPilot — 项目说明

FDM 打印过程异常诊断与安全动作决策系统。**合成遥测环境，非实机控制**——一切对外表述都必须保持这条边界（`printpilot info` 会打印它）。

## 技术栈

- Python 3.12/3.13，uv 管理依赖；pydantic v2 全程做节点间契约
- LangGraph 1.x：管线已装配为 `StateGraph`（`workflow/graph.py`，闭环每轮经图运行，唯一条件边在门禁裁决处）；框架不校验节点写回是实测缺口（ADR 0001），**任何节点都必须经 `workflow.validating_node` 包装**。设计的 3 LLM + 3 确定性节点全部实现；默认管线为规则诊断 + 规则决策（由消融证据决定），LLM 经 `eval --diagnoser llm*`、`loop --decider llm`、`loop --reflect` 进入
- LLM 走 OpenAI 兼容端点（当前 DeepSeek 官方，`json_object` 模式）；chromadb 做 RAG 向量库（懒加载，但必须留在依赖表里——首个洁净 CI 环境因缺它而失败）

## 常用命令

- 建环境：`uv venv --python 3.12` → `uv pip install -e ".[dev]"`
- 全套检查（提交前必过）：`uv run ruff check . ; uv run mypy ; uv run pytest`
- CLI 入口：`uv run printpilot <info|dataset|eval|compare|rag|loop|llm-check|skills>`
- 核心测试离线可跑（`MockLLMClient`），不需要 API key；覆盖率下限 80% 由 pytest 配置强制

## 配置（.env，永不提交）

- 对话端点：`OPENAI_API_KEY` + `PRINTPILOT_LLM_BASE_URL / _LLM_MODEL / _LLM_BACKEND / _LLM_STRUCTURED_MODE`
- embedding 独立配置：`PRINTPILOT_EMBEDDING_BASE_URL / _API_KEY`（DeepSeek 官方无 /v1/embeddings，走中转；免费档每日限 100 次请求，故有持久缓存 `.chroma/embedding-cache.json`）

## 结构（src/printpilot/）

主管线（`workflow/graph.py` 的 StateGraph）：`simulator`（故障注入+虚拟传感器，图外）→ `perception`（确定性特征提取）→ `diagnosis`（规则基线 / LLM+Skills 注入）→ `decision`（动作计划，只能提议；规则默认 + `decision/llm.py` 消融臂）→ `safety`（SafetyGate 硬约束裁决，LLM 不可绕过，条件边在此路由）→ `execution`（应用补丁/回滚）；`loop/` 闭环重打印 + 独立质量评分（图外）；`reflection/`（`loop --reflect`）复盘全轮产出候选知识卡。

支撑：`domain`（全部枚举与节点间 schema 的单一事实来源）、`llm`（客户端边界+mock）、`rag`、`skills_runtime`（SKILL.md 注册/校验/路由）、`harness`(有界并发/成本/trace)、`eval`（指标/McNemar/逐案例记录）。

各目录有 `_MAP.md` 代码地图（本地导航用，已 gitignore，可随时重新生成）。

## 硬规则（违反即错误）

1. `evals/runs/*.json` 是报告里每个数字的证据——**永不删除、永不覆盖**。
2. 跨模型的运行不做配对比较：`compare_runs` 会拒绝，这是设计而非缺陷。
3. README 引用的数字必须能从落盘记录复算（`test_readme_consistency.py` 会查）。
4. 安全指标（堵塞误入参数路径率）不单独引用，必须与准确率、弃权率并排呈现。
5. 提交：里程碑式中文提交信息，直接推 main（github.com/gsd-150/printpilot）。
6. CLI 输出是中文——新增输出路径要考虑非 UTF-8 控制台（`cli.main()` 已统一 reconfigure，教训来自 CI 的 cp1252 崩溃）。
7. Reflection 产物只写 `knowledge/candidate_cases/` 隔离区，`reflection/` 模块里不得出现写 `accepted/` 的路径（有结构性测试盯着）；候选入库 = 人工审核 + `git mv` + `printpilot rag build`，流程见 `knowledge/README.md`。复盘输入永不包含注入故障的 ground truth。
8. `knowledge/accepted/`、`prompts/diagnosis/` 等被严格 glob 的内容目录里不得放任何非内容 `.md` 文件（加载器会大声失败，这是设计——`_MAP.md` 曾因此炸过测试）。

## 代码约定

- mypy strict + ruff `ANN`：公开函数全类型注解；行宽 100；路径一律 pathlib（`PTH`）
- 标识符英文，文档/注释/CLI 输出中文（`RUF001-003` 为此有意关闭）
- 每个子包在 `__init__.py` 显式导出；对外入口是单一动词函数（`perceive` / `diagnose` / `decide` / `review`）
- 错误用途专用异常类（`NodeContractError`、`ExecutionRefusedError`、`IncomparableRunsError`…），不静默吞
- 架构决策写 ADR 进 `docs/decisions/`，含实测小节
- 知识冲突优先级：硬件安全规则 > 经审核的 Skill > 有来源的 RAG 证据 > LLM 自身知识；被覆盖的低优先级来源记入 trace
