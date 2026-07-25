# 019-A 花钱资格审计与零成本前置门禁执行报告

执行日期：2026-07-25  
分支：`task/019a-spending-eligibility-audit`  
真实 provider 调用：0  
实际支出：¥0  
最终状态：COMPLETE  
机械裁决：**丙——双臂影子录制**

## 1. 结论先行

019-A 的 A0–A11 全部完成。六项核心审计结论为：

- A1 `FIXED_IN_A`：统一 LLM 调用轨迹已补齐 cost/cache 字段，stub Reflector 调用能记录 model、输入、输出、tokens、cost、latency。
- A2 `STABLE_NORMALIZED`：reflection replay key 已去除非语义 run_id；相同语义输入跨运行逐字稳定。
- A3 `NO_LEAK`：含反思的全图 stub 运行中，LLM 占位洞察未进入其他 12 条决策的 inputs；只有确定性反思 signals 可进入 DecisionContext。
- A4 `INJECTABLE`：候选注入可落在 `research_refine` 内、写入 `next_research_intent` 之前，并复用现有 NodeContract、AgentDecision 与 DecisionGate。
- A5 `EXECUTABLE`：DeepSeek 与 qwen 计价可机械计算，单次实际成本超过预估 2 倍会抛错并中断。
- A6 `GUARDED`：密钥、实验条件盲化、公开正文三面均有守卫；公开摘录上限为 1,000 字符。

业务门禁 A7 得到 HIGH 15、MEDIUM 7、LOW 8，不触发分支 F。A8 在 `DEEPRESEARCH_MODE=llm` 且 11 个超集开关全部通过环境置 true 时，以手写固定 stub 和本地 fixture 完成全图：报告、结构化表、审计包、快照、轨迹全部生成，DecisionGate 拦截 0，引用闭合为 `ok`。

按任务卡机械表，A1 已录制 + A2 键稳定 + A4 INJECTABLE，唯一结论为丙。但当前真实模式 replay 仍有一个明确前置缺口：`replay_trajectory()` 对非 deterministic 轨迹直接返回 cache miss，且 strict/strategy 目前使用同一匹配实现。因此“可进入 019-B”只表示可以开始两项零成本工单；在候选注入和真实 LLM 轨迹离线严格回放对 A8 stub 轨迹全绿前，仍禁止支出。

## 2. 审计对象清单

| 模块 | 文件路径 | 关键符号 |
|---|---|---|
| Reflector 双轨与键 | `src/deepresearch_agent/reflection.py` | `ReflectionReasoningInterface`、`SyntheticFixtureReflectionReasoner`、`RecordedReflectionReasoner`、`Reflector`、`reflection_request_key` |
| 统一 LLM 边界 | `src/deepresearch_agent/llm/client.py` | `LLMClient.complete`、`LLMCallResult`、`CostOverrunError`、`_completion_with_retries`、`_cost_cny` |
| 模型与计价配置 | `src/deepresearch_agent/llm_config.py` | `ModelPricing`、`LLMConfig.pricing_by_model`、`RoleModelConfig` |
| 轨迹 | `src/deepresearch_agent/trajectory.py` | `LLMCallTrace`、`AgentTrajectory`、`TrajectoryRecorder`、`active_trajectory_recorder` |
| 回放 | `src/deepresearch_agent/trajectory_replay.py` | `ReplaySearchProvider`、`ReplayStructuredDataProvider`、`ReplayPlanner`、`replay_trajectory` |
| DecisionContext | `src/deepresearch_agent/orchestration/decision_context.py` | `DecisionContext`、`build_decision_context`、`_reflection_signals` |
| 图与重规划 | `src/deepresearch_agent/workflow/engine.py` | `_node_contracts`、`_contract_graph`、`_research_refine_node`、`_reflector_node` |
| 契约闸 | `src/deepresearch_agent/orchestration/contracts.py` | `NodeContract`、`DecisionGate`、`enforce_node_contract` |
| 能力选择 | `src/deepresearch_agent/tools/capability_selector.py` | `DeterministicCapabilitySelector`、`classify_subquestion` |
| 判官盲化 | `src/deepresearch_agent/evaluation/judge.py` | `EXPERIMENT_CONDITION_TERMS`、`redact_judge_report`、`JudgeClient.score` |
| 内容安全 | `src/deepresearch_agent/security/content.py` | `redact`、`detect_injection`、`wrap_untrusted` |
| 审计包 | `src/deepresearch_agent/audit_bundle.py` | `PUBLIC_EXCERPT_CHAR_LIMIT`、`export_audit_bundle`、`extract_report_claims` |
| 结构化交付 | `src/deepresearch_agent/structured_output.py` | `build_structured_output`、`render_structured_json`、`write_structured_table` |
| 研究快照 | `src/deepresearch_agent/research_snapshot.py` | `ResearchSnapshot`、`ChangeType`、`build_research_snapshot` |
| 守卫测试 | `tests/unit/test_spending_eligibility.py` | `SpendingEligibilityAuditTests`、`StubLLMReflectionReasoner` |

## 3. A1–A8 逐项事实与机械证据

### A1：LLM 调用可录制性

真实调用链已定位为：

`ReflectionReasoningInterface` 实现 → `LLMClient.complete` → `_completion_with_retries` → `active_trajectory_recorder` → `LLMCallTrace` → `TrajectoryRecorder.write`。

Planner、Extractor、Reporter 的真实生成也都复用同一 `LLMClient`。审计发现原有 `LLMCallTrace` 记录 model、prompt、response、tokens、latency，但没有 cost；这是“可回放且可花钱审计”所需的真实缺口。本轮在 8 行生产改动内补入 `cost_usd`、`cost_cny`、`price_source`、`cache_hit` 并接线。

机械命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_reflector_llm_call_records_replayable_costed_trace -v
```

输出摘要：`Ran 1 test ... OK`。测试用手写 completion stub 驱动一次 typed Reflector reasoner，断言轨迹中 role=`reflector`、model=`openai/deepseek-v4-flash`、prompt_tokens=1000、completion_tokens=500、cost_cny=0.002、cost_usd=0.00028。

诚实边界：工作流默认 `Reflector()` 当前仍使用 `SyntheticFixtureReflectionReasoner`，并非真实 LLM reasoner；本轮证明统一边界可记录真实调用，不宣称真实 Reflector 判断已经接入或有效。

### A2：回放键稳定性

reflection key 原先把执行身份 `trajectory_summary.run_id` 纳入哈希，语义相同的跨运行请求会 miss。本轮只去除 run_id，不放宽其余语义字段；编码仍为 sorted-key、紧凑 JSON 的 SHA-256。

机械命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_reflection_replay_key_is_stable_across_run_ids -v
```

输出摘要：`Ran 1 test ... OK`；同一请求重复计算和两个不同 run_id 的语义相同请求均得到逐字相等 key。

两种回放的实际键事实：

- web_search：逐字 `(query, top_k, source_type)`，按同键 FIFO。
- web_fetch：逐字 URL，按 URL FIFO。
- structured provider：全局 FIFO + operation + 该操作全部期望输入。
- planner：逐字 topic + depth_level。
- reflection：去除 run_id 后的 `deterministic_signals + trajectory_summary` 归一化 JSON SHA-256。
- `required_calls` 只是 `tool:<name>` / `llm:<role>` 的存在性标签。
- strict 与 strategy 当前没有不同匹配语义，mode 只是结果标签。
- 非 deterministic 轨迹当前明确返回 real-mode replay deferred cache miss。

最后两点是 019-B 的硬前置事实，不能把“键稳定”混称为“真实模式已可重放”。

### A3：DecisionContext 污染

`DecisionContext` 只读取 `reflection_result.deterministic_signals`，没有 `llm_insight` 字段。A8 的含反思 stub 全图状态被再次机械扫描。

机械命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  _collab/019a_spending_eligibility_audit/run_a3_check.py
```

完整关键输出：

```text
reflection_present=True
llm_insight_status=recorded_placeholder
deterministic_signals_present=True
other_decision_count=12
llm_insight_in_other_decision_inputs=False
recorded_placeholder_in_other_decision_inputs=False
```

另有既有守卫 `test_deterministic_signals_change_next_replanning_intent` 证明确定性 signals 会改变下一轮 query，而明确注入的字符串 `THIS MUST NOT ENTER A QUERY` 不进入 query 或 decision inputs。裁决：`NO_LEAK`。

### A4：候选注入位

机械探针读取运行时 NodeContract 和方法源代码：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  _collab/019a_spending_eligibility_audit/run_a4_probe.py
```

关键输出：

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

具体注入位是 `_research_refine_node` 中 `refine_research_plan()` 返回之后、`state.metadata["next_research_intent"] = refined` 之前。设计不增加新图节点：形成两份 query-map 候选，全部录制；选择器产生 `AgentDecision` 并由现有 DecisionGate 校验；只把选中候选交给 `research_prepare`。契约草案详见 `audit_verdict.md`。

裁决：`INJECTABLE`。本卡按明确禁止项没有实现候选级重规划。

### A5：计价与熔断

官方文档获取日为 2026-07-25：

- DeepSeek V4 Flash：缓存命中输入 ¥0.02/百万 tokens、缓存未命中输入 ¥1/百万、输出 ¥2/百万；来源 `https://api-docs.deepseek.com/zh-cn/quick_start/pricing/`。
- 阿里云百炼固定版本 qwen3.7-plus，北京区输入不超过 256K 时输入 ¥2/百万、输出 ¥8/百万；256K–1M 时输入 ¥6/百万、输出 ¥24/百万；来源 `https://help.aliyun.com/zh/model-studio/model-pricing`。
- 百炼隐式缓存命中按输入价格 20% 计；来源 `https://help.aliyun.com/zh/model-studio/context-cache`。本项目未启用的显式缓存折扣没有用于计算。

实现新增 typed `ModelPricing` 分层表；未知模型继续使用已有兼容价格，但已知 qwen 超过配置的 1M prompt tier 会 fail closed。`LLMClient.complete(expected_cost_cny=...)` 在 ledger 落账后检查单次实际成本；超过预估 2 倍抛 `CostOverrunError`，不是只记录日志。

机械命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_provider_pricing_and_two_times_overrun_fuse -v
```

输出摘要：`Ran 1 test ... OK`。构造 qwen usage 的精确费用为 ¥0.00568；构造 DeepSeek 实际 ¥0.001804 对预估 ¥0.0008 触发异常并中断。

### A6：三重泄漏面

1. 密钥：`redact()` 现在会动态替换环境中名字含 KEY/TOKEN/SECRET/PASSWORD 且长度至少 8 的值；provider 最终异常在抛出前 redaction。trace 失败项仍只保存 error type。
2. 判官盲化：先删除整个“Agent 决策记录”和“决策链”章节，再处理条件词。词表为 `Reflector`、`REFLECTION_ENABLED`、`reflection_result`、`reflector_placeholder`、`made_by`、`experimental_arm`、`treatment_arm`、`control_arm`、`实验组`、`对照组`。
3. 第三方正文：公开审计包只写最多 1,000 字符摘录、完整正文 SHA-256 和截断标识；文本与结构化输出统一 redaction；`.gitignore` 新增 `data/raw/`，原有 `.env`、`data/runtime/`、`runs/` 保持覆盖。

机械命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_environment_secret_is_redacted_from_provider_error \
  tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_judge_report_redaction_removes_experiment_condition \
  tests.unit.test_spending_eligibility.SpendingEligibilityAuditTests.test_audit_bundle_redacts_secrets_and_caps_public_excerpts -v
```

输出摘要：`Ran 3 tests ... OK`。审计包测试扫描包括 XLSX 的所有文件字节，完整假 key 及其尾段均为 0 命中。

### A7：30 题可检索性

未发起检索，只读取冻结题面的 topic/gold/来源描述。机械计数：

```text
HIGH=15
MEDIUM=7
LOW=8
total=30
high_threshold_met=True
```

推荐六题为 Q01、Q04、Q16、Q19、Q26、Q28，分别覆盖基础财报、机制解释、错误前提证伪、交易额口径、项目事件链和行业多源时间线。完整逐题理由见 `question_retrievability.md`。

人工边界：这只是公开来源类型与口径通常可得性的人工判读，没有证明执行日网页可访问、provider 能召回或金标准本身完整。

### A8：全开关 stub 全图冒烟

运行配置逐项开启：

`TRAJECTORY_RECORD_ENABLED / BRANCH_BUDGET_ENABLED / RESEARCH_LOOP_ENABLED(max=2) / PRIOR_MEMORY_ENABLED / DECISION_WEAVING_ENABLED / NUMERIC_CHECK_ENABLED / DYNAMIC_CAPABILITY_ENABLED / REFLECTION_ENABLED / CONTEXT_PACKER_ENABLED / INJECTION_GUARD_ENABLED / SKILL_PACKS_ENABLED`。

搜索与结构化 provider 固定为本地 fixture，模型 completion 显式替换为手写函数，`network_calls=0`。无默认值翻转。

关键完整输出：

```text
network_calls=0
status=done
metric_rows=4
timeline_events=6
risk_items=1
audit_citation_closure=ok
snapshot_claims=6
trajectory_exists=True
agent_decisions=16
decision_gate_blocked=0
graph_contract_validation=passed_at_engine_init
```

四类主产物：

- 报告：`_collab/019a_spending_eligibility_audit/a8_stub_package/report.md`
- 结构化表：`structured.json`、`structured.md`、`structured.xlsx`
- 审计包：`audit_bundle/`
- 快照：`research_snapshot.json`

LiteLLM 导入时打印两条可选 Bedrock/SageMaker `botocore` 缺失 warning；手写 stub 已替换 completion，运行没有 provider 网络调用，且项目未为消除可选 warning 新增依赖。

## 4. 三项必做实现与守卫测试

### A2 必做实现

- 改动：reflection 请求键去除非语义 run_id，其余字段、排序和哈希不变。
- 守卫：`test_reflection_replay_key_is_stable_across_run_ids`。
- 断言没有弱化：新增跨 run_id 相等和相同对象重复计算相等；未删除任何既有字段断言。

### A5 必做实现

- 改动：DeepSeek/qwen typed 分层定价；构造 usage 费用计算；2× 单次成本硬异常。
- 守卫：`test_provider_pricing_and_two_times_overrun_fuse`。
- 断言没有弱化：同时要求精确费用和异常类型/实际值/预估值；ledger 必须先留下超支记录供审计。

### A6 必做实现

- 密钥守卫：`test_environment_secret_is_redacted_from_provider_error`。
- 盲化守卫：`test_judge_report_redaction_removes_experiment_condition`。
- 版权/公开产物守卫：`test_audit_bundle_redacts_secrets_and_caps_public_excerpts`。
- 断言没有弱化：新增全文二进制扫描、尾段扫描、摘录长度、哈希等值和 `.gitignore` 覆盖；没有删除、skip 或 xfail。

### 其他测试改动理由

- `test_reflector_llm_call_records_replayable_costed_trace`：固化 A1 修复后的最低可花钱轨迹合同。
- `StubLLMReflectionReasoner`：只用于手写零网络调用，不引入 mock 依赖或新生产抽象。
- `test_spending_eligibility.py` 是本轮唯一新增测试文件改动；332 行全部对应六个独立守卫及 stub 辅助，没有修改既有测试。

## 5. 有界改造与超界工单

| 子改造 | 生产范围 | 测试/总量判断 | 结论 |
|---|---:|---|---|
| A1 轨迹成本字段 | 8 行、2 文件 | 含 stub 守卫约 130 行 | 有界，实施 |
| A2 key 归一化 | 8 行、1 文件 | 含守卫约 36 行 | 有界，实施 |
| A5 provider 分层价格 | 约 95 行、2 文件 | 单独守卫后仍低于 150 行估计 | 有界，实施 |
| A5 2× 熔断 | 约 33 行、1 文件 | 单独守卫约 50 行 | 有界，实施 |
| A6 动态 secret redaction | 11 行、2 文件 | 含守卫约 48 行 | 有界，实施 |
| A6 judge 盲化 | 36 行、1 文件 | 含守卫约 63 行 | 有界，实施 |
| A6 审计包公开边界 | 24 行+1 ignore、2 文件 | 含守卫约 96 行 | 有界，实施 |
| 真实 llm-mode strict replay | 预计 180–260 行、4–6 文件 | 超过两项阈值 | 不实施，WO-019B-02 |
| 双臂候选注入 | 预计 120–150 行、2–3 文件 | A4 明确禁止本卡实现 | 不实施，WO-019B-01 |

A5 的价格表和熔断是两个可独立验证的改造子项，虽在同一 conventional commit 中交付，各自均未超过阈值；没有用拆文件方式隐藏一个超界单体改造。

本轮没有使用“预登记外真因授权条款”：所有已修真因都在 A1/A2/A5/A6 明确授权范围内。

## 6. 裁决表

| 机械条件 | 本轮事实 | 结果 |
|---|---|---|
| A4=INJECTABLE | 是 | 丙条件 1 成立 |
| A2 键可稳定 | 是 | 丙条件 2 成立 |
| A1 已录制 | FIXED_IN_A | 丙条件 3 成立 |
| A3=LEAK_FOUND | 否，NO_LEAK | 不触发甲淘汰缺陷 |
| 最终设计 | 三条件同时成立 | **丙：双臂影子录制** |

预登记草案把四项上限固定为 ¥2 + ¥10 + ¥10 + ¥3 = ¥25，分别覆盖 provider 预飞行、六题双臂录制、盲化 judge/citation_support、精确 cache-miss 补录。每项都有机制层与质量层可证伪假设、A/B/不确定处置、回滚触发和三层熔断。

草案状态仍为 DRAFT。未经 PM 明确确认，不得支出。

## 7. 30 题预筛结论与推荐题集

HIGH 15 题：Q01、Q02、Q03、Q04、Q05、Q07、Q09、Q11、Q14、Q16、Q18、Q19、Q23、Q26、Q28。  
MEDIUM 7 题：Q06、Q10、Q13、Q15、Q17、Q25、Q29。  
LOW 8 题：Q08、Q12、Q20、Q21、Q22、Q24、Q27、Q30。

首轮六题：

1. Q01：财报基础数值与产品拆分。
2. Q04：收入降、利润升的机制解释。
3. Q16：错误前提证伪。
4. Q19：license-out 总额与首付款口径。
5. Q26：匈牙利工厂计划、开工、投产状态时间线。
6. Q28：行业自律的多源事件时间线。

不把 Q08、Q12、Q20、Q21、Q22、Q24、Q27、Q30 用于 019：它们存在错误前提、跨公司口径换算、金标准覆盖不足、模糊人物或事件错配等高混淆因素。

## 8. stub 全图产物样例

报告实际正文片段：

```markdown
## 摘要
本次零网络 stub 研究同时覆盖年度业绩口径、欧洲工厂时间线与风险；所有事实结论均引用本地 fixture 证据，不能外推为真实模型质量。

## 关键发现
- 宁德时代 2024 年累计营业收入为 3620.13 亿元。 [^1]
- 宁德时代 欧洲工厂 投产日期为2025年6月。 [^2]
- 宁德时代 20241231 累计营业收入为3.62013e+11元。 [^3]
```

一条实际决策链文本：

```markdown
- 重规划承接 Critic 未解决问题：问题类型 ['unverified_projection']；下一轮结果为 `refined_queries={'catl_performance': ['宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？ resolve unverified_projection: Projection claim has low extraction confidence: 宁德时代 欧洲工厂 投产日期为2025年6月。', '宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？ resolve critic evidence gap']}`。
```

结构化样例的计数为 MetricRow 4、ComparisonTable 1、EventTimeline 6、RiskMatrix 1；审计包 manifest 必要字段 10/10，快照 claims 6。

## 9. A9 交付清单结果

机械结构下限：

- 必要业务章节缺失 0。
- 结论 claim 6，带脚注 6，结论引用率 1.000。
- 未闭合脚注 0；占位符命中 0。
- MetricRow 4/4 字段完整；Timeline 6/6；Risk 1/1。
- audit citation closure=`ok`；manifest 必要字段 10/10；封面免责存在。
- 快照 claims 6、manifest_ref 非空、structured objects 存在；比较 schema 六类 change type 齐全。

人工通读发现两条真实质量门槛在 stub 上不通过：

1. 关键发现与详细分析逐字重复同三条，缺少从事实到含义的分析推进。
2. 同一收入同时展示 `3620.13亿元` 和 `3.62013e+11元`，科学计数法不适合直接给分析师阅读。

第三条具体观察是正向边界：摘要明确写出本地 fixture 和不可外推质量，避免把结构冒烟误当模型效果。

上述门槛已在付费前写死到 `deliverable_checklist.md`。019-C 不得结果倒推放宽。

## 10. 真实模式与 fixture 模式的结构差距

A8 使用 llm workflow 路径但 completion 是手写 stub，因此只暴露结构性问题，不是模型效果：

- Reporter 允许结构化官方 Evidence 以原始元单位的科学计数法进入面向读者正文。
- stub 生成的关键发现与详细分析缺乏层次；真实模型是否改善尚无证据。
- fixture 搜索的第三条风险 query 召回了泛金融 AI 治理来源，说明小样本中检索相关性仍可能污染报告，即使引用闭合为 100%。
- RiskMatrix 非空由一个刻意构造的低置信投产日期 projection 触发，只证明 schema 路径，不证明真实风险识别质量。

预登记已把这些现象设为 019-C 的质量否决条件；若真实模式复现，开关保持 dark，并应进入 README 的真实模式边界说明。

## 11. 遗留清单与风险

1. `SyntheticFixtureReflectionReasoner` 仍是默认 Reflector reasoner；真实 LLM 判断质量为未验证。
2. llm-mode trajectory 离线 replay 当前 fail closed；WO-019B-02 完成前禁止付费录制。
3. strict 与 strategy replay 尚未形成不同语义；不得声称已有意图级策略回放。
4. 双臂候选生成、隔离检索和 selector 尚未实现；WO-019B-01 完成前丙只是设计结论。
5. 成本是官方价格与 provider usage 的护栏估算，不是供应商发票；alias 促销未用于固定基线。
6. A7 没有访问网络，不能证明来源实时可达或 provider 召回。
7. judge 条件词表是显式闭集；若未来报告出现新的臂标识，必须扩词表并加守卫。
8. 动态环境 secret redaction 只覆盖名称特征和最低长度；所有新凭据类型仍须在安全测试中登记。
9. 公开正文上限与 hash 已实现，但真实抓取落盘路径仍须在 019-B 预飞行验证确实使用 `data/raw/` 或其他 ignored runtime 路径。
10. 本机仍未执行任何付费 API、真实 Tavily/AKShare 网络或第三方 judge；效果结论全部保留未验证状态。

## 12. 诚实声明

机械验证：

- A1 轨迹字段、A2 key 稳定、A3 无 inputs 泄漏、A4 注入序位与契约、A5 费用和 2× 异常、A6 三重守卫、A8 全图结构、A9 交付计数、最终 347 tests/Ruff/characterization/chaos/site。

人工判读：

- A7 的 30 题 HIGH/MEDIUM/LOW。
- A8 报告的三条可读性评语。
- 有界改造的子项行数估计和 019-B 工单范围估计。

尚无证据支持：

- Reflector 真实判断是否有用。
- LLM 洞察候选是否优于确定性候选。
- 真实网络召回率、fact accuracy、judge 稳定性、真实发票成本。
- 真实 llm 轨迹能否严格离线回放。
- 任一 content-affecting 开关应转正。

因此本报告只授权向 PM 提交 019-B/C 预登记草案，不授权花钱，也不授权修改任何默认开关。

## 13. 冻结资产、默认值与依赖

- `data/golden_set/`：0 改动。
- `docs/evaluation.md`：0 改动。
- `pyproject.toml`：0 改动。
- 新依赖：0。
- 默认开关：0 个翻转；A8 只用环境覆盖。
- 删除/skip/xfail：0。
- 冻结资产元数据变更申报：无。
- push/merge/tag/rebase/amend：均未执行。

## 14. 验证记录

基线：

```text
Python 3.12.10
ruff 0.15.15
Ran 341 tests in 15.774s
OK
```

每个六个代码 commit 前均执行全量 tests、Ruff 0.15.15、prompt drift、characterization、chaos、静态站构建，原始输出保存在 `_collab/019a_spending_eligibility_audit/precommit_*`。

最终闸门：

```text
Python 3.12.10
ruff 0.15.15
Ran 347 tests in 16.077s
OK
All checks passed!
prompt drift guard passed: 5 prompts
Ran 2 tests in 0.077s
OK
Ran 8 tests in 0.233s
OK
built <repo>/site/dist
files 13
validation ok
```

一次最终闸门尝试人为加入了 `STRUCTURED_LOGGING_ENABLED=false`，两条 characterization 正确报告默认 flag 从 true 变 false；这是错误的验证命令覆盖，不是代码失败。失败原始输出保存在 `final_*_invalid_logging_override.txt`。随后删除该覆盖，以项目默认配置重跑并得到上面的全绿结果；没有修改 golden 或断言。

## 15. 提交记录

`git log --oneline main..HEAD` 原始输出：

```text
c400125 fix: sanitize public audit artifacts
46bf4a1 feat: blind judge inputs to experiment conditions
9a6627c fix: redact configured secrets from provider errors
b657b94 feat: enforce provider cost guardrails
dca8756 fix: normalize reflection replay keys
0f10d7a fix: record LLM cost in replay trajectories
```

`git diff main --stat` 原始输出：

```text
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
```

工作树在最终报告写入前无已跟踪未提交修改；`_collab/` 为项目规定的 ignored 协作与运行证据目录。

## 16. 自检

- 更生产化：成本由 provider/model tier 计量并硬熔断；真实调用可形成可对账轨迹；公开产物默认收敛正文；判官输入盲化。
- demo-only 风险：A8 明确只是 stub 结构冒烟，报告和清单均禁止外推模型质量。
- 确定性 MVP：默认开关和 Golden 行为未改，最终 characterization 全绿。
- 范围控制：未实现 A4 明确禁止的候选重规划；超界真实 replay 写工单。
- 面试可解释性：可以明确说明为什么一次 paid super-trajectory 要先解决键、隔离、盲化、成本和版权五个工程门禁，以及为什么六题小样本只能否决质量、不能证明优越。

最终处置：**019-A COMPLETE；满足分支 A（全绿·丙）；可提交 PM 审核 019-B/C 预登记，但在 PM 确认且两项零成本工单全绿前继续禁止任何支出。**
