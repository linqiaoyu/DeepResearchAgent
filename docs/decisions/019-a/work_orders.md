# 019-B 零成本前置工单

这些项目不把 019-A 标记为 INCOMPLETE：候选级重规划在 A4 被任务卡明确禁止实现，真实模式 replay 也超出 A2 的“键归一化”必做范围。但它们是丙方案第一笔支出前的硬前置项；未完成时预算保持 ¥0。

## WO-019B-01：双臂候选注入与隔离录制

- 真因：当前 `_research_refine_node` 只生成一个确定性 `next_research_intent`，`reflection_result.llm_insight` 被明确标为未使用；不存在可同时执行并隔离记录的两组候选。
- 预计范围：120–150 行生产代码、2–3 个生产文件，另加测试；虽接近 A 卡有界阈值，但 A4 明确“不实现候选级重规划”，故留给 019-B。
- 契约：复用现有 `research_refine` NodeContract、AgentDecision、DecisionGate、CapabilityRegistry、ToolSpec 和分支预算；不得新建平行决策日志或绕过预算。
- 守卫：两臂查询及 tool calls 均进入同一超集轨迹；实验臂 Evidence 不进入主臂报告；选中候选属于已录候选集；任一臂越过预算即硬失败。

## WO-019B-02：真实 LLM 轨迹离线严格回放

- 真因：`replay_trajectory()` 当前对 `request.mode != deterministic` 立即返回 `cache_miss="real-mode replay is deferred until a real trajectory is recorded"`；`strict` 与 `strategy` 也尚无不同匹配行为。
- 预计范围：180–260 行生产代码、4–6 个文件（`trajectory_replay.py`、LLM 回放 adapter、engine 接线、reflection 接线及契约/配置），超过 150 行且超过 3 个文件，因此 019-A 不实施。
- 守卫：从 A8 的 llm-mode stub trajectory 离线重放必须零网络、零 cache miss，并逐字复现 report；缺少任一 role/tool 调用必须 fail closed；strict 不允许意图级放宽；strategy 若需要宽松键必须单独定义并审计。
- 付费闸：本工单对 A8 stub 轨迹全绿之前，不得执行 `preregistration_draft.md` 的任何支出项。
