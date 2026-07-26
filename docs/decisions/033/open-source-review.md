# 033 开源 Agent 架构调研与许可证审查

## 结论

2026-07-26 调研了五个仍在维护的 Agent 项目。采用的是可由本仓库事故验证的设计
原则，不是它们的运行时代码。本轮没有复制、翻译或改写第三方源码，也没有新增依赖；
因此没有第三方署名文件或许可证正文需要随本轮代码分发。仓库自身目前没有发行
许可证，故“第三方许可证兼容”只能表述为：所考察项目许可证允许借鉴，且本轮实际
复制代码量为零；不能据此宣称本仓库已经具备对外分发许可。

## 调研清单

| 项目与审查版本 | 它重点解决的问题 | 本轮采用 | 本轮放弃 | 许可证 |
|---|---|---|---|---|
| [LangGraph 1.2.9](https://pypi.org/project/langgraph/) | 低层状态图、持久化、长运行工作流和条件边 | 继续使用现有 `StateGraph`；把停止原因、失败终态和 replay 视为显式状态合同 | 不升级本地已锁定的 1.2.2，不引入 LangChain/Deep Agents，也不让框架替代本项目的决策合同 | [MIT](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) |
| [Pydantic AI 2.14.1](https://pypi.org/project/pydantic-ai/) | 类型化 tool 输出、可区分的模型重试与工具失败、依赖注入 | 采用“失败类型决定 retry/degrade/fail-closed”的思路；semantic judge 使用严格 Pydantic 输出 | 不引入第二套 Agent runner；不把校验错误自动交回模型无限修复 | [MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) |
| [OpenAI Agents SDK 0.18.3](https://pypi.org/project/openai-agents/) | 显式 turn 上限、guardrail、handoff 与覆盖 LLM/tool/guardrail 的 tracing | 借鉴 component activity、终止原因与失败 span 都应可见；`run.py`/内部模块分层作为 `engine.py` 后续拆分参考 | 不采用其 runner、handoff 或 provider 绑定；本卡消融没有证明更多角色能带来质量 | [MIT](https://github.com/openai/openai-agents-python/blob/main/LICENSE) |
| [Google ADK 2.5.0](https://pypi.org/project/google-adk/) | 确定性 workflow、stateless Runner、session/long-term memory 分层及 trajectory evaluation | 借鉴 working/episodic/procedural 必须有不同生命周期与读写证据；共享 Runner 不应暗藏跨 run 可变状态 | 不引入 ADK；没有把 session memory 的存在当成“第二次运行必然更好” | [Apache-2.0](https://github.com/google/adk-python/blob/main/LICENSE) |
| [Microsoft Agent Framework 1.12.0](https://pypi.org/project/agent-framework/) | middleware、checkpoint、workflow、可观测性与多 provider | 借鉴工具故障必须形成统一中间层事件，并把失败终态纳入 checkpoint/replay 合同 | 不引入其 runtime；本仓库已有 LangGraph，双框架会制造生命周期和 checkpoint 所有权冲突 | [MIT](https://github.com/microsoft/agent-framework/blob/main/LICENSE) |

## 对本仓库的具体影响

1. `ToolErrorKind`、有界 retry、总 deadline、circuit breaker、degradation event 和
   失败 replay 组合成一个失败合同；这直接对应 031 “只测成功路径”和“失败不可回放”。
2. Reporter 的 prompt context 与 canonical Evidence 分离，避免 working memory 为节省
   token 而删掉审计事实；这对应本卡真实消融发现的 Evidence 7→5/6。
3. Semantic judge 只负责完整性、相关性、回答形状和语义支持，数值保真仍由机械合同
   负责；这对应 031 A5 已证明“可回放的 LLM 文本仍能写错数字”。
4. `engine.py` 仍是上帝对象。OpenAI Agents SDK 的“入口只负责 orchestration，内部
   runtime 分模块”是后续目标，不是本轮已完成事实。一次性迁移整个执行器会扩大风险，
   本轮先抽出 reporting context、grounded fact renderer 和 semantic judge 三个边界。
5. 五个项目都提供更多 Agent/runner 能力，但本轮没有任何消融证据支持新增角色。
   因此没有更换编排框架、没有新增重型依赖，也无需重大产品决策 ADR。

## AGENTS.md 结构参考

仅参考了 [OpenAI Agents SDK 的 AGENTS.md](https://github.com/openai/openai-agents-python/blob/main/AGENTS.md)
和 [Google ADK 的 AGENTS.md](https://github.com/google/adk-python/blob/main/AGENTS.md)
如何把入口边界、公共合同和测试责任放在靠前位置。最终规则内容只取自本仓库
021–031 的事故或本仓库明确风险；没有复制两份文件的规则文本。
