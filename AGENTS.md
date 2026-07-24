# AGENTS.md

## 1. 项目定位与当前状态

DeepResearchAgent 是一个多 Agent 深度研究框架，金融投研为首个落地场景。

当前仓库处于 MVP 阶段：已实现确定性的 Planner、Researcher、Extractor、Critic、Reporter、Evaluator 工作流；默认使用本地 fixture 检索数据与录制结构化金融数据；编排层已迁移为 LangGraph `StateGraph`，Researcher 按子问题 fan-out，Critic 通过条件边回流 retry queue；checkpoint 由官方 `SqliteSaver` 写入 SQLite，Evidence 和 evaluation 结果由 `SQLiteStore` 写入 SQLite；LLM 模式通过统一 LiteLLM 层覆盖 Planner、Extractor、Reporter，Researcher 与 Critic 当前仍保持确定性；已接入 AKShare 白名单结构化数据边界、五元素数字 claim 口径体系、金融化 Critic；Golden Set v1.1 已以四键审计闸冻结（76 PASS、0 DEFECT、3 条 PM 注记 UNCERTAIN），并完成 G1/G2/G3 保存态三采样重评；007/007S 已加入三层演示资产（G3 展示层、异步 Golden replay 重跑层、owner-token live 层）与持久化日消耗护栏，公开触达形态为静态演示站，由 `scripts/build_site.py` 生成 `site/dist/` 后手工上传；010 新增工具契约、安全、运行血统、上下文打包、结构化日志与配置校验层，以及只读离线评测工具；011 用双题面规范化快照证明 010 默认路径与 `befd60b` 产物等价，默认启用工具契约、run manifest、结构化日志与 fail-fast，新增八场景离线 chaos 演练，并把注入语料扩为 63 条；012 修复 context packer 的同 URL 多摘录去重缺陷但继续保持 dark，新增结构化产出、引用闭合审计包、独立 ResearchSnapshot、manifest-aware 六类变更追踪、默认关闭的 API 章节轮询与 fixture 业务场景页；013 修正结构化产出转正规则并将其在 deterministic 默认路径启用，以 `additive_content` 标记其可比性边界，同时查明 fixture 引用崩塌来自 Reporter/Evaluator 的位置脚注排序漂移，记录方法边界、可读变更呈现、模拟成本标签与保存态延迟；014 新增统一 `AgentDecision`、结构化轨迹与 fixture 严格/策略回放，并把 Reporter 脚注映射固化为跨消费者契约；015 新增覆盖全图节点的 `NodeContract`、LangGraph 原生有界研究回边、分支预算、确定性情景/语义记忆、最近两期研究行为与 `CapabilityRegistry`，三个 content-affecting 策略开关均保持默认关闭；context packer、injection guard、progressive delivery 与 trajectory recording 仍保持 dark，结构化产出的 LLM additive 性仍须在后续授权任务验证；010 耦合审计判定金融逻辑仍硬编码于核心 Agent，`domains/finance` 与 `domains/competitive` 尚未落位，不得宣称框架已完成领域解耦；当前主推理模型锁定 deepseek-v4-flash，judge 与 citation_support 锁定 qwen3.7-plus；CLI demo、LLM smoke、Golden Set runner、FastAPI demo endpoints、静态站构建和 unittest 套件已在本地 `.venv` 验证过相应路径。

本项目是作品集和演示导向项目，但实现选择仍应能解释为生产化工程决策。

016 已新增只读 `DecisionContext` 编织预算、充分性、跨期分类与 Critic 问题，加入四类
数值自洽校验、基于 `CapabilityRegistry` 的确定性动态能力选择和扩展轨迹严格回放。
三项新增 `content_affecting` 开关均默认关闭；017–019 的既定后续路线见第 13 节。

017 已完成 Reflector 双轨骨架：四类确定性跨轮信号、独立 LLM 推理接口及合成/录制
占位、严格 cache miss、程序性记忆与反思驱动重规划接线均已落位。该轮只证明管道，
反思判断质量与跨运行策略偏好优劣待 019 真实验证。

018 已完成零依赖 MCP 双向边界与首个 Skill pack：标准库 stdio server 暴露四个
fixture 工具，标准库 client 可发现外部工具并注册回 `CapabilityRegistry`；skill loader
按 metadata-first 渐进披露，金融口径规则以相同 SHA-256 等价迁移。Claude Code
完成 `initialize` / `initialized` / `tools/list` 健康检查，但第三方客户端的完整
`tools/call` 握手仍为 INCOMPLETE；完整调用序列仅由自建最小客户端验证，不得混称。

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
- `docs/`：架构、评估、方法边界、部署、provider、威胁模型、SLO、生产就绪度、MCP 与 skill 文档。
- `prompts/`：当前存在五个角色 prompt 与 `registry.json` 漂移登记表。
- `scripts/`：除运行入口外，包含 manifest 比对、prompt 漂移、只读 run 对比、离线指标、Golden schema 校验、审计包导出、业务快照创建与快照差异工具。
- `skills/`：metadata-first 运行时 skill packs；当前仅有金融数值口径归一 pack。
- `src/deepresearch_agent/`：包源码，包含 `agents/`、`api/`、`context/`、`evaluation/`、`mcp/`、`memory/`、`observability/`、`orchestration/`、`provenance/`、`security/`、`skills/`、`storage/`、`tools/`、`workflow/`。
- `tests/`：`unit/`、`integration/`、`evaluation/`、`chaos/` 四类 unittest 测试，并以 `golden_output/` 固化双题面行为快照。
- `ui/app.py`：Streamlit UI 入口。
- `pyproject.toml`：项目元数据、依赖、脚本入口和 Ruff 配置。

领域目录约定（尚未实施）：目标 domain pack 包含 `tools/`、`prompts/`、`templates/`、`eval/`、`domain.yaml` 五类；新增领域前必须先完成 finance 等价抽取、旧路径兼容、资源 SHA-256 与默认 E2E 行为证明。

当前默认开关：`TOOL_CONTRACT_ENABLED=true`、`INJECTION_GUARD_ENABLED=false`、`RUN_MANIFEST_ENABLED=true`、`CONTEXT_PACKER_ENABLED=false`、`STRUCTURED_LOGGING_ENABLED=true`、`CONFIG_FAIL_FAST_ENABLED=true`、`STRUCTURED_OUTPUT_ENABLED=true`、`PROGRESSIVE_DELIVERY_ENABLED=false`、`TRAJECTORY_RECORD_ENABLED=false`、`BRANCH_BUDGET_ENABLED=false`、`RESEARCH_LOOP_ENABLED=false`（max iterations 默认 1）、`PRIOR_MEMORY_ENABLED=false`、`DECISION_WEAVING_ENABLED=false`、`NUMERIC_CHECK_ENABLED=false`、`DYNAMIC_CAPABILITY_ENABLED=false`、`REFLECTION_ENABLED=false`、`SKILL_PACKS_ENABLED=false`。任何跨代比较必须先经 `scripts/verify_manifest.py` 判定。

## 3. 技术栈与版本

- Python：`>=3.11`；本地 `.venv` 验证版本为 Python 3.12.10。
- 项目版本：`deepresearch-agent==0.1.0`。
- Pydantic：`>=2.0`。
- FastAPI：`>=0.110`。
- Uvicorn：`uvicorn[standard]>=0.27`。
- Streamlit：`>=1.35`。
- LangGraph：`pyproject.toml` 声明 `langgraph>=0.2.50`；本地 `.venv` 实际安装版本为 1.2.2。当前工作流代码已使用 LangGraph 图执行；015 首次在研究主路径通过 conditional edge 使用原生有界回边，`BoundedLoop` 只提供边界状态而不替代执行器。
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

011 产物级 characterization：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_snapshot_run -v
```

011 离线故障演练：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_SEARCH_PROVIDER=fixture DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture .venv/bin/python -m unittest discover -s tests/chaos -v
```

012 审计包导出（deterministic + fixture）：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/export_audit_bundle.py --topic '宁德时代 2024 年业绩与欧洲工厂扩张研究' --as-of 2026-07-09 --output _collab/012_business-layer/audit_bundle_demo --structured-output
```

012 业务快照创建与变更比较：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/create_research_snapshot.py --topic 'AI Agent 在财富管理行业的落地机会研究' --as-of 2026-07-09 --output _collab/012_business-layer/snapshots/wealth_2026-07-09.json
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/diff_snapshots.py _collab/012_business-layer/snapshots/wealth_2026-07-09.json _collab/012_business-layer/snapshots/wealth_2026-07-24_demo.json --markdown _collab/012_business-layer/demo_diff.md --json _collab/012_business-layer/snapshots/demo_diff.json --summary _collab/012_business-layer/snapshots/demo_summary.txt
```

012 静态站业务场景构建：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_site.py
```

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
- 冻结资产的任何元数据变更必须在执行报告中单列申报，说明字段、原因、影响边界和是否触及评分契约。
- 对已证明只新增产物、不改动既有产物的开关执行转正时，默认值翻转与
  `tests/golden_output/` 更新组成一个原子提交对：第一个 commit 只翻默认值，
  第二个 commit 只更新 golden。绿灯闸门作用于提交对完成之后，不作用于
  中间态；仅第一个 commit 允许 characterization 因预期的 golden 差异为红。
  两个 commit 必须连续，中间不得插入其他改动，提交对完成后必须立即运行
  全量绿灯闸门。
- manifest flag 分为三类：`content_affecting` 会改变既有内容并阻断可比性；
  `additive_content` 只新增产物对象、不改动既有产物，不阻断既有指标可比性，
  但必须在比较输出中显式列出；`operational` 只形成信息性差异。未知 flag
  必须 fail closed。分类证明只在其明确验证过的运行模式内成立。
- `docs/method_limits.md` 是 characterization 与 fixture 质量指标的正式方法边界。
  能改变 Evidence 集合或顺序的控制不得只凭 fixture 质量数字转正，须按该文档
  的适用性检查和真实模式验证要求执行。
- 只执行提示词明确列出的事项。
- 发现提示词与仓库现实冲突时，停止该项、在报告中说明，不得自行扩大范围或自行决策。
- 一个 Codex 执行者负责每轮任务端到端闭环；不要使用 `.agent_handoff` 式交接，不要拆分为 Architect/Executor 多 Codex 角色，不要把任务扩展到无关模块。
- 产品内部的 Planner、Researcher、Extractor、Critic、Reporter、Evaluator 是领域组件，不是 Codex 开发角色。
- Reporter 产生的 `report_footnote_evidence` 是引用解析契约；Evaluator、审计导出与其他消费者不得根据当前 Evidence 顺序重建脚注映射。历史状态缺少映射时必须显式降级。
- 新增 Agent 决策能力必须复用 `AgentDecision`，并同步进入结构化 trace、manifest 决策摘要和读者可见报告。轨迹录制默认关闭，真实轨迹须经单独授权。
- 016/017 新增节点、循环、记忆或工具能力时，必须分别复用 `NodeContract`、`LoopSpec`、`MemoryStore` 与 `CapabilityRegistry`；不得绕过 DecisionGate、预算、ToolSpec 或 manifest flag 分类。

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

## 12.1 CI 与依赖纪律

- CI 中所有工具依赖（当前的 Ruff，以及未来任何 lint、format、test、type-check 工具）必须钉死精确版本，且必须与本地 `.venv` 使用的版本一致。CI 的职责是复现本地环境，不是寻找一个恰好能通过的版本；禁止在 CI 中使用无上限的版本约束（如 `tool>=x`）。
- 引入或升级任何工具依赖时，必须同步更新 CI 中钉死的版本号，并在本地使用该精确版本验证全套闸门通过后才可提交。
- CI 与本地必须使用同一 Python 解释器解析方式：测试与脚本调用解释器时使用 `sys.executable`，不得写死 `.venv` 或任何环境特定的绝对路径，以保证在没有 `.venv` 的 CI 环境中同样可运行。

本纪律源于一次 Ruff 浮动版本事故：CI 对未改动代码报出 131 条新诊断；可复现是本项目第一原则。

## 13. 既定后续路线（不可默默取消）

本节使 017/018/019 成为仓库事实源的一部分。任何后续任务若要跳过或缩减它们，必须显式在报告中申报并给出理由，禁止无声推迟。

### 017（骨架已完成；LLM 接入与判断力待 019）

- Reflector 已读取 AgentTrajectory 与全部 AgentDecision，机械提取持续薄弱项、反复无效来源、重复 Critic issue 与无进展重规划轮次；`REFLECTION_ENABLED=false`，`content_affecting`
- 双轨结构已落位：确定性信号可 fixture 验证；类型化 LLM 推理接口本轮仅合成/录制占位，真实判断质量待 019
- 反思驱动重规划已复用 015 的精化接口、016 的 DecisionContext 与 BoundedLoop；只有确定性信号参与，llm_insight 不参与
- ProceduralMemory 已实现 MemoryStore，`lifecycle=cross_run`，按问题类型索引策略—充分性—反思观察；不自动选择策略，跨真实运行偏好优劣待 019
- Reflector 已声明 NodeContract；信号提取与程序记忆写入均形成 AgentDecision 并经 DecisionGate；扩张轨迹可严格逐字回放

### 018（实现已完成；第三方完整 tools/call 握手 INCOMPLETE）

- MCP server 已用 Python 标准库实现 stdio JSON-RPC 2.0，目标协议 `2025-06-18`；把 `CapabilityRegistry` 机械映射为 tool schema，暴露发起研究、取回证据、导出审计包、比较两期快照四个 deterministic fixture 工具
- 本机 Claude Code 已实际完成 `initialize` / `notifications/initialized` / `tools/list` 健康检查；因其没有零模型直接 `tools/call` 命令，第三方完整握手为 INCOMPLETE。自建标准库客户端已完成含一次成功 `tools/call` 的全序列，但不得表述为第三方握手
- MCP client 已消费外部 stdio server 的工具并命名空间化注册进同一 `CapabilityRegistry`；发现形成 `AgentDecision`，调用沿用 ToolSpec、超时、重试、降级与付费确认边界
- Skill packs 已实现 metadata-first 渐进披露，选择与加载均形成 `AgentDecision`；首个金融数值口径 pack 是 1299 字节、SHA-256 不变的等价迁移，只是 010 领域耦合债的首付
- `SKILL_PACKS_ENABLED=false` 且分类为 `content_affecting`；MCP 与 skill 扩张轨迹已在 fixture 下严格回放。全轮零新增依赖、零真实 API、零费用

### 019（付费验证轮）

- 每笔支出前须在 preregistration.md 写明：支出项、预算上限、可证伪假设、测量方法、决策规则（满足条件A则点亮/回滚/接受，条件B则另一动作，两者都不满足则停止交 PM）。无预登记的支出一律禁止
- 顺序：预飞行（tool contract 真实 provider 验证，¥1–2）→ 录制超集轨迹（016 阶段 6 给出配置，¥5–8）→ 离线回放验证全部可离线开关（¥0）→ 仅 cache_miss 且必要时申请新支出
- 每项点亮必须同时定义回滚触发条件
- 硬熔断三层：单项预算上限、全轮总预算上限（建议 ¥20）、意外支出检测（单次实际成本超预估 2 倍即停止）
- 禁止无假设的全量 G4：除非确实点亮了改变内容生成的开关，否则不跑三十题全量回归；若点亮则跑针对性定向对照
- 整轮成功判据：产出一份真实模式完整研究包、至少两个 dark 开关依据预登记规则得到明确处置、产出一条可严格回放的真实轨迹、总花费在预算内且每笔可追溯到预登记假设
