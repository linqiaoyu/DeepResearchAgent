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
