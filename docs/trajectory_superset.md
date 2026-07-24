# 019 轨迹录制超集

## 016 最扩张配置

019 的真实超集录制应开启：

`TRAJECTORY_RECORD_ENABLED=true`、`BRANCH_BUDGET_ENABLED=true`、
`RESEARCH_LOOP_ENABLED=true`、`DECISION_WEAVING_ENABLED=true`、
`NUMERIC_CHECK_ENABLED=true`、`DYNAMIC_CAPABILITY_ENABLED=true`、
`REFLECTION_ENABLED=true`、`SKILL_PACKS_ENABLED=true`，并将
`DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS=2`、研究调用预算设为 20、
no-progress window 设为 5。录制题面必须同时触发结构化数据与 web search，并包含至少
一个可核验数值关系。两轮足以覆盖首轮、重规划、第二轮与停止边；后续单轮或关闭部分
开关的保守策略都落在这组调用类型之内。

这只是 019 的配置建议；016 没有录制真实轨迹，也没有发生 API 支出。

## 捕获完整性

轨迹 schema v2 保留并验证：

- 每次 LLM 调用（本轮 deterministic 合成轨迹预期为 0）、本地工具调用、节点转移和
  `AgentDecision`。
- 016 的每次能力选择、数值核验、预算分配、循环控制与重规划。
- 017 `Reflector` 读取轨迹策略信号的 `signal_reads`，以及
  `ProceduralMemory` cross-run 写入的 `memory_writes`。
- 018 MCP 外部调用仍进入统一 `tool_calls`，以 `transport=mcp` 与 `server` 标识，
  不另造平行轨迹。
- 018 skill 选择与资源加载仍进入统一 `agent_decisions`；录制题面必须实际命中
  `finance-metric-normalization`，同时保留一个不适用判定样本证明资源未被提前加载。

019 录制 MCP 面时，只连接精确配置并显式信任的本项目 stdio server；至少记录一次
`tools/list` 后的非付费 fixture 调用。MCP 服务端的 deterministic 调用不替代真实模式
研究，也不计作质量证据；若要让外部 MCP 工具触发付费 provider，必须另列预登记支出项
并显式传入 `allow_paid=true`。MCP 与 skill 的 fixture 接线均不能证明研究质量提升。
