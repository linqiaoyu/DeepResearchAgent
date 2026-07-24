# 研究编排契约

## 为什么需要这一层

LangGraph 负责节点执行、条件边、`Send` 扇出和 checkpoint；它并不知道本项目的
业务字段应由谁产生、由谁消费。项目已有两次事故都发生在这个空白处：

- Reporter 已产出 `report_footnote_evidence`，Evaluator 却曾按 Evidence 当前顺序
  重新构造脚注关系。运行没有报错，`unresolved=0` 仍可能是静默错误。
- context packer 会改变 Evidence 集合。八个局部单测全绿时，它仍曾让整体证据量
  丢失约 80%，说明跨节点的 Evidence 保持约束没有被声明。

编排契约层把这类约定变成图的属性。图构建时，消费项找不到前序生产者会立即失败；
节点运行时，缺少消费字段、没有写出声明字段、破坏不变式或决策节点没有记录
`AgentDecision` 都会抛出 `ContractViolationError`。错误包含节点、契约项、期望、
实际结果和经脱敏的 state 键摘要。

## NodeContract

`NodeContract` 有四个组成部分：

- `consumes`：state 路径到 `ContractField` 的映射，声明类型与是否必需。
- `produces`：节点返回值必须明确写出的 state 路径。
- `invariants`：接收节点前后 state 的可执行谓词。
- `decision_node`：启用 `DecisionGate`，要求本次执行新增至少一个
  `AgentDecision`。

现有十二个节点均已声明契约。尤其是 Reporter 明确生产
`research_state.report_footnote_evidence`，Evaluator 明确消费同一路径。
这使脚注映射成为 Reporter 到 Evaluator 的强制交接合同，而不是消费者自行推断。

图构建校验只读取一个最小拓扑视图；真实执行仍完全由 LangGraph 完成。运行期包装器
只在节点边界前后检查 state，不改变节点业务逻辑或 LangGraph 合并语义。

## 明确不做什么

这一层不替换 LangGraph，不实现调度器，不定义工作流 DSL，也不做图的序列化或
可视化。它不判断研究结论是否正确；它只强制已声明的数据和决策交接约束。

## 后续消费者

016 增加节点或 LLM 驱动决策时，必须同时声明其 `NodeContract`，决策节点必须启用
`DecisionGate`。017 的 skill 节点同样在注册进图时提供消费、生产和不变式声明。
未来若节点可能裁剪或重排 Evidence，应声明 Evidence 身份/覆盖不变式，而不能只用
节点内部单测证明安全。

## LoopSpec 与 BoundedLoop

`LoopSpec` 声明 `max_iterations`、`budget_ceiling`、`no_progress_window`、
可注入的 `progress_metric` 和 `on_exhausted`。`BoundedLoop` 把具体研究策略作为
`step` 注入，并用 LangGraph `StateGraph` 的 conditional edge 从
`loop_decide` 回到 `loop_iteration`。此前项目虽然使用 LangGraph，但研究主路径
实际上是 DAG；这是项目首次使用其原生的带条件循环能力。控制器没有自建调度器。

每轮都记录一个 `bounded_loop_control` 类型的 `AgentDecision`，包括前后度量、预算、
无进展计数、触发边界、判据、结果和备选项。轮次、循环预算、连续无进展三条边界
任一触发即停止；已完成工作保留在 `ResearchState`。耗尽会写入
`metadata.research_loop.coverage_warning`，若报告已经存在也会附加“因 X 边界停止，
覆盖可能不足”。

循环预算与工具层 `RetryBudget` 是两套正交账本：前者只计研究轮的主调用或 token，
后者只计一次工具主调用内部的重试。`LoopIterationResult.retry_budget_consumed` 仅作
决策审计输入，不会再次累加进循环预算，因此不双重计费；循环剩余预算为零时不会
调用策略，所以低层重试也不能绕过循环边界。阶段 5 才会把充分性策略接入该控制器。

## BranchBudget 与 Send 扇出

`BranchBudget(total_budget, per_branch_cap)` 是一次运行内的并行分支账本。当前接入以
`search_calls` 为预算单位。`research_prepare` 在 LangGraph `Send` 扇出之前按分支
均分；每个 `research_one` 只能执行其获配的搜索调用数；`research_join` 汇总实际
用量和每支来源/结构化证据数，再调用 `reallocate`。再分配保留已用额度，把剩余容量
优先给度量较低的分支，并始终受单支上限与总上限约束，不做运行中的动态抢占。

初始分配与再分配分别记录 `branch_budget_allocate` 和
`branch_budget_reallocate` 决策，输入包含每支度量、逐支额度、总量、已用量、单支
上限和理由。分支额度耗尽只停止该分支并标注覆盖不足；总额度耗尽让全部分支收敛，
已完成结果仍进入 join。该行为由默认关闭、归类为 `content_affecting` 的
`BRANCH_BUDGET_ENABLED` 控制；关闭时不创建账本、决策或产物差异。阶段 5 将在研究
轮次之间复用 join 后的再分配结果。
