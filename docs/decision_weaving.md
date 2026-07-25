# 决策编织

## 目的

015 已有循环、分支预算、跨期记忆和能力注册，但各自读取局部状态。016 新增
`DecisionContext`，让后续决定显式继承已经发生的决定及其输入，回答“Agent 如何通盘
权衡”，同时保持 LangGraph 为唯一执行器。

## 只读上下文

`build_decision_context` 从 `ResearchState` 生成深只读 Pydantic 值对象，字段包括：

- `BudgetContext`：总预算、已用/剩余、单支余额、verify 最低额度；
- `SufficiencyContext`：每个子问题的充分性度量、轮次和进展；
- `PriorClassificationContext`：最近期 verify/watch/explore 结果；
- `CriticIssueContext`：未解 issue、严重级别、Evidence IDs 与可选数值公式；
- 已发生决定的类型、actor、outcome 与 iteration。

调用方只能读取，不能借共享引用修改状态。新的事实仍必须通过图节点产出并由
`NodeContract` 校验。

## 三条真实依赖

1. **历史分类 → 预算**：verify 分支在预算再分配中至少保留
   `DEEPRESEARCH_DECISION_WEAVING_VERIFY_MIN_ALLOCATION`，除非总预算已经耗尽。
2. **预算 → 循环**：剩余比例低于
   `DEEPRESEARCH_DECISION_WEAVING_BUDGET_REMAINING_RATIO` 时，即使尚未命中旧的硬上限，
   循环也提前收敛，并在决定与报告中写明预算约束。
3. **Critic 问题 → 重规划**：重规划直接读取上下文中的未解问题；数值自洽问题会携带
   公式与 Evidence IDs 形成定向补证意图，不再依赖调用方另传一份可能漂移的 issue 列表。

动态能力选择也发生在同一图边界：它读取子问题类型和历史分类，只从
`CapabilityRegistry` 的当前快照挑选能力，再由 Researcher 执行。

## 为什么这是 Agent，而不只是流水线

流水线中的节点只接收固定输入并执行固定下一步；决策编织后的节点会在相同契约边界内，
根据本轮预算、已经观察到的充分性、上期任务类型和刚出现的 Critic 缺口改变后续动作，
而且能指出该动作依赖了哪些先前事实。这里的“Agent”指有界、可审计的状态依赖决策，
不等同于自由规划，也不赋予系统扩大范围或支出的权限。

它明确不做两件事：`DecisionContext` 不是任意节点可写的全局可变状态；选择规则也不引入
LLM 判断。所有变化仍通过 LangGraph 状态、`NodeContract`、`DecisionGate`、预算和
ToolSpec 边界发生。

## 决策链呈现

当开关开启时，Reporter 追加“决策链”章节，按结构化记录顺序展示预算分配/再分配、循环
停止、上期分类、检索重规划、数值校验和能力选择。每条记录只呈现可审计输入、明确判据、
结果和被拒绝替代项，不暴露或伪造隐藏思维过程。Evidence ID 使用稳定标识。

## 配置与可比性

```text
DECISION_WEAVING_ENABLED=false
DEEPRESEARCH_DECISION_WEAVING_BUDGET_REMAINING_RATIO=0.2
DEEPRESEARCH_DECISION_WEAVING_VERIFY_MIN_ALLOCATION=1
NUMERIC_CHECK_ENABLED=false
DYNAMIC_CAPABILITY_ENABLED=false
```

三项功能开关均归类为 `content_affecting`。关闭时对应 flag 和参数从 manifest 的实验配置
中省略，保留 015 默认路径逐字等价；开启后 manifest 必须记录开关、阈值、能力规则和完整
decision summary，跨代比较由 `scripts/verify_manifest.py` fail closed。

## 回放

016 的扩展轨迹 schema 记录 LLM、search、fetch、structured provider、节点、决定、
signal reads 和 memory writes。严格 fixture 回放恢复原计划和策略配置，并要求报告逐字一致；
未录制调用会令严格回放 fail closed。策略级回放尚未实现；真实轨迹仍需单独授权，当前仅
验证离线超集。

## 方法边界

fixture 能证明三条依赖确实触发、预算不越界、数值公式可复算、能力不会绕过 registry、
轨迹可严格回放。它不能证明这些策略对真实网页排序、LLM 抽取、覆盖度、引用质量、延迟和
成本的净效果。019 之前不得将“已接线”表述为“研究质量提升”。
