# AGENTS.md

## 1. 项目定位与当前状态

DeepResearchAgent 是一个多 Agent 深度研究框架，金融投研为首个落地场景。

当前仓库处于 MVP 阶段：已实现确定性的 Planner、Researcher、Extractor、Critic、Reporter、Evaluator 工作流；默认使用本地 fixture 检索数据与录制结构化金融数据；编排层已迁移为 LangGraph `StateGraph`，Researcher 按子问题 fan-out，Critic 通过条件边回流 retry queue；checkpoint 由官方 `SqliteSaver` 写入 SQLite，Evidence 和 evaluation 结果由 `SQLiteStore` 写入 SQLite；LLM 模式通过统一 LiteLLM 层覆盖 Planner、Extractor、Reporter，Researcher 与 Critic 当前仍保持确定性；已接入 AKShare 白名单结构化数据边界、五元素数字 claim 口径体系、金融化 Critic；006R3 已冻结 Golden Set v1，006V 已用 qwen3.7-plus 重评 G1，006F2 已移除 reporter 词法回填并以 evidence_ids 修复重试完成 G3 同判官闭环；007/007S 已加入三层演示资产（G3 展示层、异步 Golden replay 重跑层、owner-token live 层）与持久化日消耗护栏，公开触达形态改为静态演示站，由 `scripts/build_site.py` 生成 `site/dist/` 后手工上传；007S gold 只读审计发现 7 条 REVIEW 项且 AKShare live 全部失败，待 PM 决定是否递增 v1.1；当前主推理模型锁定 deepseek-v4-flash，judge 与 citation_support 锁定 qwen3.7-plus；CLI demo、LLM smoke、Golden Set runner、FastAPI demo endpoints、静态站构建和 unittest 套件已在本地 `.venv` 验证过相应路径。

本项目是作品集和演示导向项目，但实现选择仍应能解释为生产化工程决策。

## 2. 仓库结构

- `.env.example`：环境变量示例文件。
- `.github/workflows/ci.yml`：GitHub Actions CI 配置。
- `.gitignore`：本地忽略规则。
- `AGENTS.md`：协作规范。
- `Dockerfile`、`docker-compose.yml`：容器与 compose 配置。
- `README.md`：项目说明文档。
- `_collab/`：任务提示词、执行报告和本地验证产物目录。
- `artifacts/`：已有 demo、eval、checkpoint 等运行产物。
- `data/`：评测集、Golden Set v1、bad cases、mock source fixture、demo 展示资产和 runtime 数据。
- `docs/`：架构、评估、部署、provider 集成和面试问答文档。
- `prompts/`：当前存在 `critic.md`、`extractor.md`、`judge.md`、`planner.md`、`reporter.md`。
- `scripts/`：`run_demo.py`、`run_eval.py`、`run_golden_round.py`、`run_checkpoint_demo.py`、`dev_server.py`、`record_structured_data_fixture.py`。
- `src/deepresearch_agent/`：包源码，包含 `agents/`、`api/`、`evaluation/`、`storage/`、`tools/`、`workflow/` 以及 `schemas.py`、`settings.py`、`citations.py`、`cli.py`。
- `tests/`：`unit/`、`integration/`、`evaluation/` 三类 unittest 测试。
- `ui/app.py`：Streamlit UI 入口。
- `pyproject.toml`：项目元数据、依赖、脚本入口和 Ruff 配置。

## 3. 技术栈与版本

- Python：`>=3.11`；本地 `.venv` 验证版本为 Python 3.12.10。
- 项目版本：`deepresearch-agent==0.1.0`。
- Pydantic：`>=2.0`。
- FastAPI：`>=0.110`。
- Uvicorn：`uvicorn[standard]>=0.27`。
- Streamlit：`>=1.35`。
- LangGraph：`pyproject.toml` 声明 `langgraph>=0.2.50`；本地 `.venv` 实际安装版本为 1.2.2。当前工作流代码已使用 LangGraph 图执行。
- LangGraph SQLite Checkpointer：`pyproject.toml` 声明 `langgraph-checkpoint-sqlite>=3.1.0,<4.0.0`；本地 `.venv` 实际安装版本为 3.1.0，`from langgraph.checkpoint.sqlite import SqliteSaver` 已验证成功。
- LiteLLM：`>=1.40`，本地 `.venv` 实际安装版本为 1.86.2。所有真实 LLM 调用必须经过 `deepresearch_agent.llm.LLMClient`；当前 LLM 模式覆盖 Planner、Extractor、Reporter。
- AKShare：`pyproject.toml` 声明 `akshare>=1.18.64,<2.0.0`；本地 `.venv` 实际安装版本为 1.18.64。当前仅通过 `StructuredDataProvider` 白名单能力使用，测试与默认运行使用录制 fixture。
- HTTPX：`>=0.27`，用于 Tavily 搜索适配器。
- Pytest：`>=8.0`，列在依赖中；当前验证命令使用 unittest。
- Dev 依赖：`pytest>=8.0`、`ruff>=0.5`。
- Setuptools：`>=68`；Wheel：用于构建后端。

规则：未经 PM 批准不得更换编排框架、不得新增重型依赖、不得引入新的 Multi-Agent 库。

## 4. 运行与测试命令

005 已验证可用的测试命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_SEARCH_PROVIDER=fixture DEEPRESEARCH_MODE=deterministic DEEPRESEARCH_STORAGE_PATH=_collab/005_finance-pack/verification/test_research.db .venv/bin/python -m unittest discover -s tests
```

005 已验证可用的确定性金融 demo 命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_SEARCH_PROVIDER=fixture DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture DEEPRESEARCH_MODE=deterministic DEEPRESEARCH_STORAGE_PATH=_collab/005_finance-pack/comparison/deterministic.db .venv/bin/python scripts/run_demo.py --mode deterministic --topic '宁德时代 2024 年业绩与欧洲工厂扩张研究' --depth 1 --output _collab/005_finance-pack/comparison/deterministic_report.md
```

005 已验证可用的 LLM 金融 smoke 命令（需要 `.env` 中存在 `DEEPSEEK_API_KEY`，fixture 检索与结构化 fixture）：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_SEARCH_PROVIDER=fixture DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture DEEPRESEARCH_MODE=llm DEEPRESEARCH_STORAGE_PATH=_collab/005_finance-pack/smoke/run1/research.db DEEPRESEARCH_LLM_LEDGER_PATH=_collab/005_finance-pack/smoke/llm_ledger.jsonl .venv/bin/python scripts/run_demo.py --mode llm --topic '宁德时代 2024 年业绩与欧洲工厂扩张研究' --depth 1 --output _collab/005_finance-pack/smoke/run1/report.md
```

005 额外验证：`PYTHONPATH=src .venv/bin/python -m ruff check src tests scripts`。

006R3 验证过的 Golden Set v1 judge round 命令（需要 `.env` 中存在 `DEEPSEEK_API_KEY` 与 `DASHSCOPE_API_KEY`，不触发 Tavily 检索）：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_golden_round.py --questions data/golden_set/v1/questions.json --output data/golden_set/v1/results/round1.json --work-dir _collab/006r3_recording-completion/round1 --round-id round1 --as-of 2026-07-09 --ledger-path _collab/006r3_recording-completion/round_llm_ledger.jsonl --judge-samples 3 --state-path-map _collab/006r3_recording-completion/state_path_map.json
```

007 已验证 FastAPI/Uvicorn demo endpoints（展示层、方法论、报告读取、owner live 无令牌 403、护栏触顶 429）。007S 已验证异步 demo rerun 的 mock 队列/轮询/重启恢复/护栏测试和 `scripts/build_site.py` 静态站构建；本机未安装 `docker`/`podman`，因此 Docker/Compose 构建运行仍未在本地验证；Streamlit 入口未做浏览器级验证。

## 5. 编码规范

- 默认使用确定性本地测试；CI 和基础 demo 不得要求付费 API key。
- 密钥纪律：API key 只经 `.env` 读取；严禁出现在代码、日志、账本、报告、commit message 中。
- 外部 provider 必须置于工具或 agent 边界之后，保证 Tavily、LiteLLM、LangGraph、Postgres 等实现可替换时不改写工作流语义。
- 所有 LLM 调用必须经统一封装层并记录 token、cost、latency。当前 `LLMClient` 已记录 token、cost、latency、cache_hit、prompt_cache_hit_tokens、prompt_cache_miss_tokens、price_source、repair_attempts 到 `data/runtime/llm_ledger.jsonl`；deterministic 模式继续使用估算值。
- 所有外部工具调用必须有 timeout 和 retry。目标规范，现状未满足：Tavily 适配器已有 `timeout_seconds`，但未发现 retry 机制。
- prompt 文本放独立的 `prompts/` 目录，禁止硬编码在业务代码中。目标规范，现状未满足：`prompts/` 存在，但当前确定性 Planner/Reporter/Critic 相关文本和查询模板仍在业务代码中。
- 关键数据结构用 Pydantic 强类型。当前 `schemas.py` 已用 Pydantic 定义跨 Agent 合同，包括 `ResearchState`、`ResearchPlan`、`Source`、`Evidence`、`CriticReport`、`EvaluationResult` 等。
- 任何 evaluation 指标定义变更都必须同步更新 `docs/evaluation.md`。

## 6. 分支与提交工作流

- 每个任务在 `task/编号-短名` 分支进行。
- 分支上可自由 commit；commit message 遵循 conventional commits。
- 禁止在 commit message 中添加任何 `Co-Authored-By` 行。
- 禁止 `git add .` 与 `git add -A`，必须按文件路径精确 add。
- 永远禁止 push、merge、历史改写、force 操作，除非 PM 当轮明确指示。
- 审查点从 commit 前移到 merge 前：PM 审查分支 diff、执行报告和验证证据后再决定是否合并。

## 7. 运行产物纪律

- 一切运行期产物只允许写入被 `.gitignore` 覆盖的路径，包括 `*.db`、demo 输出、metrics 快照、缓存和临时报告。
- `data/eval_set_deterministic.jsonl`、`data/eval_baseline.json`、`data/golden_set/v1/`、`data/bad_cases_deterministic.jsonl`、`data/bad_cases_llm.jsonl`、`data/mock_data/`、`data/demo/` 是受管资产，必须保持追踪。
- 不得提交 `.env`、runtime 数据库、`artifacts/`、`_collab/`、缓存目录或本地生成的包元数据。

## 8. 协作协议

- 每个任务以编号提示词下发。
- 执行的第一个动作是把提示词逐字存入 `_collab/编号_短名/prompt.md`。
- 执行的最后一个动作是把执行报告存入同目录 `report.md` 并完整打印到终端。
- 执行报告必须包含 `git log --oneline main..HEAD` 与 `git diff main --stat` 的原始输出。
- 只执行提示词明确列出的事项。
- 发现提示词与仓库现实冲突时，停止该项、在报告中说明，不得自行扩大范围或自行决策。
- 一个 Codex 执行者负责每轮任务端到端闭环；不要使用 `.agent_handoff` 式交接，不要拆分为 Architect/Executor 多 Codex 角色，不要把任务扩展到无关模块。
- 产品内部的 Planner、Researcher、Extractor、Critic、Reporter、Evaluator 是领域组件，不是 Codex 开发角色。

## 9. 验证纪律

- 任何“已完成”的声明必须附带实际执行的命令和原始输出。
- 没有运行验证过的结论必须明确标注为推测。
- 诊断问题时先读代码再下结论。
- 禁止为使测试通过而弱化断言、删除用例或跳过测试。
- 所有测试文件改动必须在执行报告中逐条列出修改理由。
- 每轮任务应完成自检：是否更生产化、是否存在 demo-only 风险、是否保留确定性 MVP 行为、是否避免范围扩张、是否能在面试中清楚解释设计。

## 10. 自治模式禁止清单

Goal 或自治模式下绝对禁止 push、force push、历史改写、批量文件删除、对外网络写操作。
任何 commit 的 `amend` 与 `rebase` 均属于历史改写，即使该 commit 尚未推送；修正既有提交中的问题必须以新的 conventional commit 追加。

## 11. Review Gates

以下 gate 是里程碑审查标准，不是当前完成声明：

- Gate 1：项目骨架包含 `pyproject.toml`、Docker assets、`.env.example`、`src/`、`tests/`、`docs/architecture.md`、`docs/evaluation.md`。
- Gate 2：MVP 可从 topic 运行到带来源引用的 Markdown report。
- Gate 3：Evidence 和 Critic pass：关键 claims 能映射到 sources，Critic 能发现 missing citations、numeric conflicts、outdated sources、missing counterarguments、unverified projections。
- Gate 4：Evaluation harness 可运行，并报告 citation accuracy、relevance、faithfulness、cost、latency、tokens、bad-case categories。
- Gate 5：Release packaging demo-ready，包含 README、architecture diagram、Docker Compose、deployment notes。

## 12. Scope Guardrails

核心研究系统稳定前，不新增无关产品领域。优先打磨当前差异化能力：

- Evidence Store。
- Critic feedback loop。
- Citation verification。
- Checkpoint recovery。
- Evaluation Harness。
- Demo packaging and deployment path。
