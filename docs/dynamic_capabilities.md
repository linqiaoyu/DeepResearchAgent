# 动态能力选择

`DYNAMIC_CAPABILITY_ENABLED` 默认关闭。开启后，规划完成的每个子问题先由确定性分类器
标为 `financial_metric`、`market_price`、`verify` 或 `narrative`，再从 015 的
`CapabilityRegistry` 候选目录中选择能力。

默认规则为：

- `financial_metric`、`market_price`：优先结构化数据能力，同时保留 web search。
- `verify`：优先定向 web fetch，同时保留独立 web search。
- `narrative`：选择 web search。

规则通过 `DEEPRESEARCH_DYNAMIC_CAPABILITY_RULES_JSON` 配置。配置项只有在 registry
声明适用于该子问题类型时才会入选。每次选择均记录子问题类型、完整候选集、选中项、
落选项、判据与是否回退；落选项使“主动选择”与“固定默认”可审计地区分开。

没有匹配规则或规则没有可用能力时，选择器显式回退到 015 的
`web_search / web_fetch / structured_data_provider` 固定集合，并在
`AgentDecision` 中标记 `fallback=true`，不会静默改变执行路径。

fixture 只证明规则、回退和接线按定义执行；策略优劣与真实研究质量影响待 019 验证。
