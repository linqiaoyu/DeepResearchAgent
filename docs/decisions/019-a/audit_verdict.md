# 019-A 审计结论

结论日期：2026-07-25。总成本：¥0；真实 provider 调用：0。

| 阶段 | 裁决 | 机械证据 | 事实边界 |
|---|---|---|---|
| A1 | FIXED_IN_A | `test_reflector_llm_call_records_replayable_costed_trace` | 统一 LLMClient 现记录 model、输入、输出、tokens、cost、latency；当前工作流 Reflector 仍是录制占位，真实 reasoner 尚待 019 接入。 |
| A2 | STABLE_NORMALIZED | `test_reflection_replay_key_is_stable_across_run_ids` | reflection key 已排除执行身份 run_id，并对归一化 JSON 做排序 SHA-256；未放宽语义粒度。 |
| A3 | NO_LEAK | `run_a3_check.py` 与 `test_deterministic_signals_change_next_replanning_intent` | A8 含反思 stub 运行中，12 条非 Reflector 决策 inputs 均未出现 `llm_insight` 或 `recorded_placeholder`；确定性 signals 可进入 DecisionContext。 |
| A4 | INJECTABLE | `run_a4_probe.py` | 注入位为 `_research_refine_node` 内 `refine_research_plan()` 返回之后、写入 `next_research_intent` 之前；节点已是 decision node，出边唯一指向 `research_prepare`。 |
| A5 | EXECUTABLE | `test_provider_pricing_and_two_times_overrun_fuse` | 两 provider 计价可由构造 usage 精确计算；单次实际成本大于预估 2 倍抛 `CostOverrunError` 并中断。 |
| A6 | GUARDED | `test_environment_secret_is_redacted_from_provider_error`、`test_judge_report_redaction_removes_experiment_condition`、`test_audit_bundle_redacts_secrets_and_caps_public_excerpts` | 环境密钥动态脱敏；judge 剥除实验条件；公开审计摘录上限 1,000 字符并保存 SHA-256；raw 路径忽略。 |
| A7 | PASS | `question_retrievability.md` | 30/30 已人工判定；HIGH=15，不触发分支 F。此项是人工业务判断，不是网络可达性测试。 |
| A8 | COMPLETE | `run_a8_stub.py` | 全开关 llm 模式、fixture 工具、手写 stub；状态 done，四类产物齐全，metric/events/risks=4/6/1，引用闭合 ok，DecisionGate 拦截 0。 |

## 四行机械裁决

1. A1 = `FIXED_IN_A`，因此“LLM 调用已录制”条件成立。
2. A2 = `STABLE_NORMALIZED`，因此“回放键可稳定”条件成立。
3. A3 = `NO_LEAK`，反思占位洞察没有通过 DecisionContext 侧漏。
4. A4 = `INJECTABLE`；结合 A1 与 A2，按任务卡表格唯一落定 **丙：双臂影子录制**。

## A2 回放键事实

- web_search 严格键：逐字 `(query, top_k, source_type)`，同键以 FIFO 队列消费。
- web_fetch 严格键：逐字 URL，按 URL 的 FIFO 队列消费。
- structured provider 严格键：全局 FIFO 顺序，加逐字 `operation` 与该操作的全部期望输入字段。
- planner 严格键：逐字 `topic` 与整数 `depth_level`。
- reflection 录制键：去除 `trajectory_summary.run_id` 后，`deterministic_signals` 和其余 `trajectory_summary` 做 UTF-8、sorted-key、紧凑 JSON，再取 SHA-256；这是归一化语义请求键，不是宽松意图匹配。
- `required_calls` 只校验 `tool:<name>` / `llm:<role>` 是否存在，不参与具体响应匹配。
- 当前 `strict` 与 `strategy` 走同一匹配实现；`mode` 只是结果标签，尚无独立的策略级宽松键。
- 当前 `replay_trajectory()` 对 `request.mode != deterministic` 明确返回 cache miss。因此 A2 证明“键稳定”，不证明真实 LLM 轨迹已能离线重放；丙方案在首次支出前仍须完成 `work_orders.md` 中的零成本实现前置项。

## A4 契约变更草案

- 保持现有 LangGraph 节点，不新增平行节点或选择结构。
- 在 `_research_refine_node` 中先形成两个 `dict[sub_question_id, list[query]]` 候选：确定性候选与 LLM 洞察候选；二者都在选择前写入扩张轨迹。
- 选择器复用 `AgentDecision`，`made_by=ReplanCandidateSelector`，由现有 `research_refine` 的 `DecisionGate` 强制新增决策；输出唯一选中候选到 `research_state.metadata.next_research_intent`。
- NodeContract consumes 增补可选 `research_state.metadata.reflection_result`；produces 明确增补 `research_state.metadata.replan_candidates`、`research_state.metadata.next_research_intent`，并保留 `research_state.agent_decisions`。新增 invariant：候选集至少两臂、选中 ID 必须属于候选集、每臂 query map 必须覆盖原计划子问题。
- `research_refine -> research_prepare` 出边不变，后续 fan-out 只消费选中 intent；影子臂的检索调用通过同一 ToolSpec/CapabilityRegistry 执行并录制，但不得悄悄并入主臂 Evidence。

## 分支落点

满足分支 A（全绿·丙）的条件，但“可进入 019-B”只表示可以开始零成本的候选注入与真实模式回放实现；任何支出仍必须等待 PM 确认 `preregistration_draft.md`，并通过其中的付费前置闸。
