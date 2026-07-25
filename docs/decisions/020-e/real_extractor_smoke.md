# 020-E 决策记录：真实 Extractor 烟测

状态：INCOMPLETE。

本轮在 CATL 2022-070 一手 PDF 上执行两次真实 `openai/deepseek-v4-flash` Extractor 调用，LLM 账本总计 ¥0.008545，低于 Tier 1 ¥5 上限。Q26 路径实际发生一次 Tavily search 与一次 HTTP PDF fetch，均在 12/20 run-wide egress 上限内。

该次端到端路径得到三条 `source_tier=primary` Evidence，均被报告关键发现引用，审计 `citation_closure=ok`。这仅说明本次逐字 Evidence/引用闭合机制可运行；不构成任何模型质量、研究质量、效果或优劣结论。

严格轨迹回放返回 `cache_miss`，原因是当前 replay 对 real-mode trajectory 明确延后，因此“严格回放逐字一致”未通过，整轮不能宣称全绿。

另有一项流程限制：执行前未把独立的数值成本预估写进产物，因此无法事后验证 E1 的“预估偏差 <50%”验收；报告保留该 INCOMPLETE 事实。
