# 020-A 决策记录：工具契约从声明变为执行

状态：COMPLETE（零 LLM provider 调用、零网络验证）

`ToolSpec.timeout_s` 现在由可靠执行器强制执行：超时返回结构化 `TIMEOUT`，作为失败计入该 ToolSpec 的断路器，并由适配器写入工具轨迹。同步引入 `CircuitBreakerPolicy`，每个 ToolSpec 可配置失败阈值、恢复窗口和 half-open 探针数，历史默认值仍是 3 / 30 秒 / 1。

每次 `DeepResearchEngine.run()` 都创建新的 `RunToolContext` 并把它绑定到已注册的实现，避免 retry budget、breaker 和 egress 计数跨 run 遗留。

run-wide egress budget 以独立的 search 与 fetch 计数器工作；Tavily 的 POST/GET 和巨潮的 stock GET、query POST、PDF GET 均在请求前占用预算。超限时不发出请求、抛 `BUDGET_EXCEEDED`、保留工具 trace；engine 将运行标为 `budget_exceeded`，写入 `external_request_budget_rejected` AgentDecision，并用 DecisionGate 验证该决策确已写入状态。

机械守卫测试锁定了 `tools/` 中仅有的两个 `httpx` 文件和五个 egress 调用点；新增 `httpx` 调用点或漏掉 `_consume_egress()` 会导致测试失败。Fixture 也声明搜索会计入 `max_searches_per_run`，修复默认路径的预算空转。
