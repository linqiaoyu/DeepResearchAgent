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

当前图中的全部节点均已声明契约。尤其是 Reporter 明确生产
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
调用策略，所以低层重试也不能绕过循环边界。研究充分性策略已通过同一控制器的
`advance` 接口接入主图条件回边。

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
`BRANCH_BUDGET_ENABLED` 控制；关闭时不创建账本、决策或产物差异。研究循环启用时
会在轮次之间复用 join 后的再分配结果。

## 研究充分性循环与重规划

`RESEARCH_LOOP_ENABLED` 默认关闭并归类为 `content_affecting`；
`DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS` 默认 1。单轮配置视为有效关闭，因此
不会新增决策、manifest flag 或报告章节，双题面仍与既有快照逐字一致。大于 1 时，
Critic 通过后进入 `research_loop_decide`：充分则进入 Reporter，不足且边界未触发则
进入 `research_refine`，随后通过 LangGraph conditional edge 回到原有
`research_prepare → Send → research_join → extractor → critic` 路径。并行 fan-out
拓扑没有改写。

充分性按每个子问题确定性计算六项：

- Evidence 条数；
- 独立来源域名数；
- 平均置信度；
- 最新 Evidence 距 as_of 的天数；
- 未解决 Critic issue 数；
- 是否缺少反方/风险证据。

默认阈值依次是 2、2、0.7、365 天、0，并要求反方证据；均可由
`DEEPRESEARCH_RESEARCH_*` 环境变量配置。总分是六项归一分量的平均值，只用于进展
检测；是否充分必须逐项过闸。

不足时 Planner 的确定性重规划根据实际 gap 替换下一轮查询：来源集中则要求独立来源，
缺反方则生成风险/约束查询，时效不足则加入 as_of 限定，证据或置信度不足则要求官方/
一手复核，Critic issue 未解则生成定向补证查询。它不复用上一轮原查询。
`research_replan` 决策记录 gap、判据和新查询。每轮 join 后 `BranchBudget.reallocate`
把剩余搜索调用额度向低充分性分支倾斜；循环、分支和底层工具重试账本各自保留用途，
不会把同一重试重复计为研究轮预算。

启用时报告新增“研究过程”，逐轮展示查询、六项度量、循环决策、预算和停止边界。
轮次、调用预算、无进展任一边界耗尽都会保留既有工作，并明确写出“覆盖可能不足”。

## CapabilityRegistry

`CapabilityRegistry` 是工具能力的确定性目录。每项注册包含名称、适用的子问题类型、
成本等级、是否有副作用以及完整 `ToolSpec`，并绑定一个实现。名称、成本与副作用
标记必须和 `ToolSpec` 一致；重复注册与未知名称查询均 fail closed。查询结果按名称
排序，因此相同 registry 上的相同查询结果稳定。

当前 `web_search`、`web_fetch` 和结构化数据 provider 均已注册，Researcher 的搜索、
旧来源复核与结构化数据依赖通过 registry 的固定名称解析，不再直接把构造出的
provider 传给节点。本轮没有能力选择策略，也没有修改任何工具实现或引入插件加载。

016 可在此契约上根据子问题类型实现动态能力选择；017 的 skill packs 可把 skill
提供的能力注册到同一 registry。届时选择策略是 registry 的消费者，不应把策略塞入
注册与查询这两个基础操作。
