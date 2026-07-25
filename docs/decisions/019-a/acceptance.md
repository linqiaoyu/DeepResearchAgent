# 019-A 验收卡

以下每阶段固定为六个字段。原始输出均来自所列命令的实际执行；完整大日志另保存在同目录的 `a0_*`、`precommit_*` 和 `final_*` 文件中。

## A0

- 阶段：A0 分支与基线
- 状态：COMPLETE
- 验收命令：`{ .venv/bin/python --version; .venv/bin/ruff --version; tail -5 _collab/019a_spending_eligibility_audit/final_full_tests.txt; cat _collab/019a_spending_eligibility_audit/final_ruff.txt; cat _collab/019a_spending_eligibility_audit/final_prompt_drift.txt; tail -5 _collab/019a_spending_eligibility_audit/final_characterization.txt; tail -5 _collab/019a_spending_eligibility_audit/final_chaos.txt; cat _collab/019a_spending_eligibility_audit/final_build_site.txt; }`
- 通过判据：Python 3.12.10；Ruff 0.15.15；全量 tests ≥341 且 OK；Ruff/prompt drift/characterization/chaos/site 全绿。
- 失败含义：环境或基线不满足任务卡硬门禁，后续阶段不得继续。
- 原始输出：
```text
Python 3.12.10
ruff 0.15.15
....................................
----------------------------------------------------------------------
Ran 347 tests in 16.077s

OK
All checks passed!
prompt drift guard passed: 5 prompts

----------------------------------------------------------------------
Ran 2 tests in 0.077s

OK

----------------------------------------------------------------------
Ran 8 tests in 0.233s

OK
built <repo>/site/dist
files 13
validation ok
```

## A1

- 阶段：A1 LLM 调用可录制性
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_reflector_llm_call_records_replayable_costed_trace -v`
- 通过判据：1 test、0 failure；轨迹断言包含 model/input/output/tokens/cost/latency。
- 失败含义：真实 Reflector 调用无法形成可计费、可回放轨迹，禁止支出。
- 原始输出：
```text
test_reflector_llm_call_records_replayable_costed_trace (tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_reflector_llm_call_records_replayable_costed_trace) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.007s

OK
```

## A2

- 阶段：A2 回放键稳定性与归一化
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_reflection_replay_key_is_stable_across_run_ids -v`
- 通过判据：1 test、0 failure；相同语义输入跨不同 run_id 的 key 逐字相等。
- 失败含义：一次录制不能稳定命中，丙方案失去可重复性基础。
- 原始输出：
```text
test_reflection_replay_key_is_stable_across_run_ids (tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_reflection_replay_key_is_stable_across_run_ids) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

## A3

- 阶段：A3 DecisionContext 污染审计
- 状态：COMPLETE
- 验收命令：`{ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019a_spending_eligibility_audit/run_a3_check.py; PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_reflection.ReflectionDrivenReplanningTest.test_deterministic_signals_change_next_replanning_intent -v; }`
- 通过判据：含反思的 A8 stub 状态存在；12 条其他决策 inputs 中 `llm_insight=False`、`recorded_placeholder=False`；守卫测试 OK。
- 失败含义：纯观察前提被侧漏破坏，甲方案出局且必须先修泄漏。
- 原始输出：
```text
reflection_present=True
llm_insight_status=recorded_placeholder
deterministic_signals_present=True
other_decision_count=12
llm_insight_in_other_decision_inputs=False
recorded_placeholder_in_other_decision_inputs=False
test_deterministic_signals_change_next_replanning_intent (tests.unit.test_reflection.ReflectionDrivenReplanningTest.test_deterministic_signals_change_next_replanning_intent) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.001s

OK
```

## A4

- 阶段：A4 重规划候选注入位
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019a_spending_eligibility_audit/run_a4_probe.py`
- 通过判据：research_refine 是 decision node；注入序位在 refine 之后、next intent 写入之前；唯一出边到 research_prepare。
- 失败含义：无法在 NodeContract 内隔离两臂，丙方案不可用。
- 原始输出：
```text
node=research_refine
consumes=['research_state', 'research_state.plan']
produces=['research_state.agent_decisions', 'research_state.plan']
decision_node=True
incoming_edges=[('reflector', 'research_refine'), ('research_loop_decide', 'research_refine')]
outgoing_edges=[('research_refine', 'research_prepare')]
candidate_injection_order=552<1713
reflection_result_read=True
llm_insight_used_false=True
```

## A5

- 阶段：A5 成本计量与 2× 熔断
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_provider_pricing_and_two_times_overrun_fuse -v`
- 通过判据：构造 usage 的 qwen 成本精确为 ¥0.00568；DeepSeek 实际 ¥0.001804 > 2×¥0.0008 时抛 CostOverrunError。
- 失败含义：预算不能在流程层硬中断，禁止真实 provider 调用。
- 原始输出：
```text
test_provider_pricing_and_two_times_overrun_fuse (tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_provider_pricing_and_two_times_overrun_fuse) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.002s

OK
```

## A6

- 阶段：A6 三重泄漏面
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_environment_secret_is_redacted_from_provider_error tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_judge_report_redaction_removes_experiment_condition tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_audit_bundle_redacts_secrets_and_caps_public_excerpts -v`
- 通过判据：3 tests、0 failure；密钥、实验条件、公开正文三面守卫全部 OK。
- 失败含义：存在凭据、盲评或版权泄漏面，禁止生成付费或公开产物。
- 原始输出：
```text
test_environment_secret_is_redacted_from_provider_error (tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_environment_secret_is_redacted_from_provider_error) ... ok
test_judge_report_redaction_removes_experiment_condition (tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_judge_report_redaction_removes_experiment_condition) ... ok
test_audit_bundle_redacts_secrets_and_caps_public_excerpts (tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_audit_bundle_redacts_secrets_and_caps_public_excerpts) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.208s

OK
```

## A7

- 阶段：A7 Golden 30 题真实可检索性预筛
- 状态：COMPLETE
- 验收命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019a_spending_eligibility_audit/run_a7_check.py`
- 通过判据：总行数 30；HIGH ≥6；每行在 `question_retrievability.md` 有理由和用途。
- 失败含义：HIGH <6 触发分支 F，停止并交 PM。
- 原始输出：
```text
HIGH=15
MEDIUM=7
LOW=8
total=30
high_threshold_met=True
```

## A8

- 阶段：A8 全开关 stub provider 全图冒烟
- 状态：COMPLETE
- 验收命令：`env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_MODE=llm DEEPRESEARCH_SEARCH_PROVIDER=fixture DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture DEEPSEEK_API_KEY=[REDACTED] TRAJECTORY_RECORD_ENABLED=true BRANCH_BUDGET_ENABLED=true RESEARCH_LOOP_ENABLED=true DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS=2 PRIOR_MEMORY_ENABLED=true DECISION_WEAVING_ENABLED=true NUMERIC_CHECK_ENABLED=true DYNAMIC_CAPABILITY_ENABLED=true REFLECTION_ENABLED=true CONTEXT_PACKER_ENABLED=true INJECTION_GUARD_ENABLED=true SKILL_PACKS_ENABLED=true STRUCTURED_LOGGING_ENABLED=false .venv/bin/python _collab/019a_spending_eligibility_audit/run_a8_stub.py`
- 通过判据：network_calls=0、status=done、metric/events/risks 均 >0、closure=ok、trajectory=True、DecisionGate blocked=0、contract passed。
- 失败含义：全图或任一交付物不闭环；超界则触发分支 E。
- 原始输出：
```text
network_calls=0
research_id=<run-id>
status=done
report=<repo>/_collab/019a_spending_eligibility_audit/a8_stub_package/report.md
structured=<repo>/_collab/019a_spending_eligibility_audit/a8_stub_package/structured.json
structured_table=<repo>/_collab/019a_spending_eligibility_audit/a8_stub_package/structured.xlsx
metric_rows=4
timeline_events=6
risk_items=1
audit_bundle=<repo>/_collab/019a_spending_eligibility_audit/a8_stub_package/audit_bundle
audit_citation_closure=ok
snapshot=<repo>/_collab/019a_spending_eligibility_audit/a8_stub_package/research_snapshot.json
snapshot_claims=6
trajectory=<repo>/_collab/019a_spending_eligibility_audit/a8_stub_package/runs/<run-id>/trajectory.json
trajectory_exists=True
agent_decisions=16
decision_gate_blocked=0
graph_contract_validation=passed_at_engine_init
```

## A9

- 阶段：A9 真实模式交付清单
- 状态：COMPLETE
- 验收命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019a_spending_eligibility_audit/run_a9_check.py`
- 通过判据：章节缺失 0、结论脚注率 1.000、未闭合 0、占位 0、四类对象非空且字段完整、manifest 10/10、快照与六变更类型齐。
- 失败含义：不能把“可直接给人看”机械化，付费后会发生结果倒推阈值。
- 原始输出：
```text
missing_required_sections=0
conclusion_claims=6
cited_conclusion_claims=6
conclusion_citation_rate=1.000
unresolved_footnotes=0
placeholder_hits=0
metric_rows=4 complete_metric_rows=4
timeline_events=6 complete_events=6
risk_items=1 complete_risks=1
audit_citation_closure=ok
manifest_required_fields=10/10
cover_disclaimer=True
snapshot_claims=6 snapshot_manifest_ref=True snapshot_structured_objects=True
change_types=6/6:added_claim,disappeared_claim,numeric_change,evidence_replacement,confidence_change,scope_change
```

## A10

- 阶段：A10 甲/乙/丙与预登记
- 状态：COMPLETE
- 验收命令：`{ rg -n '^1\. A1 =|^2\. A2 =|^3\. A3 =|^4\. A4 =' _collab/019a_spending_eligibility_audit/audit_verdict.md; rg -n '小样本下质量层证据只能作为否决条件，不能作为点亮的充分条件|预算算术：.*¥25|状态：.*DRAFT' _collab/019a_spending_eligibility_audit/preregistration_draft.md; }`
- 通过判据：四行机械裁决唯一落定丙；草案明确 DRAFT、质量小样本只可否决、总预算精确 ¥25。
- 失败含义：实验设计依赖主观偏好或支出缺少预登记，禁止花钱。
- 原始输出：
```text
18:1. A1 = `FIXED_IN_A`，因此“LLM 调用已录制”条件成立。
19:2. A2 = `STABLE_NORMALIZED`，因此“回放键可稳定”条件成立。
20:3. A3 = `NO_LEAK`，反思占位洞察没有通过 DecisionContext 侧漏。
21:4. A4 = `INJECTABLE`；结合 A1 与 A2，按任务卡表格唯一落定 **丙：双臂影子录制**。
3:状态：**DRAFT，未经 PM 明确确认不得生效或支出。**
11:**小样本下质量层证据只能作为否决条件，不能作为点亮的充分条件。**
66:预算算术：¥2 + ¥10 + ¥10 + ¥3 = **¥25**。任何未列出的“顺便重跑”、全量 G4 或扩大 judge 样本均无预算授权。
```

## A11

- 阶段：A11 报告、提交与冻结边界
- 状态：COMPLETE
- 验收命令：`{ git status --short; git log --oneline main..HEAD; git diff main --stat; frozen=$(git diff --name-only main..HEAD -- data/golden_set docs/evaluation.md pyproject.toml); if [ -z "$frozen" ]; then echo 'frozen_or_dependency_changes=0'; else echo "$frozen"; fi; }`
- 通过判据：工作树无已跟踪未提交修改；六个 conventional commits；冻结资产/依赖改动数 0；最终全套闸门见 A0。
- 失败含义：提交纪律、冻结资产或依赖边界被破坏，任务不可交付。
- 原始输出：
```text
c400125 fix: sanitize public audit artifacts
46bf4a1 feat: blind judge inputs to experiment conditions
9a6627c fix: redact configured secrets from provider errors
b657b94 feat: enforce provider cost guardrails
dca8756 fix: normalize reflection replay keys
0f10d7a fix: record LLM cost in replay trajectories
 .gitignore                                 |   1 +
 src/deepresearch_agent/audit_bundle.py     |  23 +-
 src/deepresearch_agent/evaluation/judge.py |  36 +++-
 src/deepresearch_agent/llm/client.py       | 106 ++++++++-
 src/deepresearch_agent/llm_config.py       |  38 ++++
 src/deepresearch_agent/reflection.py       |   8 +-
 src/deepresearch_agent/security/content.py |   7 +
 src/deepresearch_agent/trajectory.py       |   4 +
 tests/unit/test_spending_eligibility.py    | 332 +++++++++++++++++++++++++++++
 9 files changed, 540 insertions(+), 15 deletions(-)
frozen_or_dependency_changes=0
```
