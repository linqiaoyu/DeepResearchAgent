# Agent 决策面

本项目的 Agent 不只执行固定节点，也会在显式边界内作出可审计决定。每个新增决定复用
`AgentDecision`：记录决策类型、决策者、测量输入、书面判据、结果、考虑过的替代项、
循环轮次与时间。相同对象进入结构化 trace、run manifest 的 decision summary 和
读者可见报告；`DecisionGate` 会阻止声明为决策节点却没有新增记录的执行。

## 当前真实决定

### 1. 研究循环继续、充分停止或边界停止

启用 `RESEARCH_LOOP_ENABLED` 且最大轮次大于 1 后，系统按子问题计算六项充分性度量：
Evidence 条数、独立来源域名数、平均可信度、最新证据时效、未解决 Critic issue 数、
是否缺少反方证据。`BoundedLoop` 把度量与轮次、剩余调用预算、连续无进展次数一起
判断，输出：

- `continue`：尚不充分且仍有轮次、预算与进展空间；
- `stop_sufficient`：六项均过闸；
- `stop_exhausted:*`：命中最大轮次、预算或连续无进展边界，保留已完成工作并标注
  覆盖不足。

判据不是 LLM 主观打分，默认配置也不启用多轮研究。

### 2. 预算如何划拨

启用分支预算后，`BranchBudget` 在 LangGraph `Send` 前按分支均分总调用预算，并受
单支上限约束。join 后，它按充分性度量从低到高把剩余额度拨给较弱分支。分支或总量
耗尽会停止相应工作、保留结果并写出覆盖警告；不会让低层 retry 偷用循环预算。

`branch_budget_allocate` 与 `branch_budget_reallocate` 记录每支度量、allocated /
used / remaining、总预算、单支上限、选择理由和替代方案。

### 3. 上期结论属于 verify、watch 还是 explore

启用 `PRIOR_MEMORY_ENABLED` 且存在同 question_id 的最近一期快照时，Planner 为每个
子问题选择：

- `verify`：命中置信度达标且非 uncertain 的上期 claim，需核实是否仍成立；
- `watch`：命中低置信度或 uncertain claim，需重点关注；
- `explore`：没有上期 claim 覆盖，需要寻找新信息。

`prior_memory_classification` 写明命中的 claim、confidence、as_of 和旧来源 URL。
verify 可以优先 fetch 旧来源，但必须同时保留至少一次独立检索，以避免确认偏误。

### 4. 如何精化下一轮检索意图

循环选择继续时，Planner 不会原样重跑旧查询。`research_replan` 根据具体缺口生成新
意图：来源集中则要求不同来源类型，缺反方则生成风险/反向查询，过旧则加入 as_of
限定，证据或置信度不足则要求官方一手复核，未解 Critic issue 则生成定向补证查询。
记录中同时保存旧查询、新查询、触发 gap 与替代项，可直接审计第二轮是否真正变化。

## 默认状态与权限边界

`BRANCH_BUDGET_ENABLED=false`、`RESEARCH_LOOP_ENABLED=false` 且 max iterations
默认 1、`PRIOR_MEMORY_ENABLED=false`。这些 `content_affecting` 能力在默认路径
不新增决定、不改报告，两题面 characterization 保持逐字一致。确定性测试只证明
判据、边界和产物可重复，不能证明它们提高真实 LLM 研究质量。

人工仍负责研究题目、provider 与费用授权、来源许可与材料性、预测审批、对外发布，
以及所有投资或交易决定。Agent 无权自行联网付费、发布、交易或扩大研究范围。

## 后续接入

016 的 LLM 充分性/能力选择或程序性记忆必须继续使用 `AgentDecision` 和现有
`BoundedLoop` 边界；017 skill packs 的选择决定必须通过同一审计落点。动态工具与
skill 只能从 `CapabilityRegistry` 取能力，不能绕过 ToolSpec、预算或节点契约。
