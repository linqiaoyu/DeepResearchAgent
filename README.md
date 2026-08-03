# DeepResearchAgent

把投研结论带回可核对的来源，而不是交付一段无法复查的文字。

## 你会拿到什么

下面内容逐字来自 `artifacts/087/live-nio-zh/report.md`。

<!-- BEGIN 087 EMBEDDED REPORT -->
# 蔚来 2024 年年报的营收与毛利情况

数据截至：2025-04-08

免责声明：本报告为研究性输出，不构成投资建议。

## 摘要
本报告围绕“蔚来 2024 年年报的营收与毛利情况”拆解为 1 个子问题，累计抽取 31 条证据。当前 Critic 质量分为 1.00，首要结论可追溯到来源 [^1]。

## 关键发现
- 毛利：NIO Inc. 2024年 年度毛利为6,492,762,000 CNY。 [^1]
- 营业收入：NIO Inc. 2024年 年度营业收入为65,731,559,000 CNY。 [^1]

## 派生指标
- 毛利率（推导值）：6,492,762,000 / 65,731,559,000 = 9.88% [^1] [^1]

## 指标覆盖状态
- 毛利（请求报告期：2024）：NIO Inc. 2024-12-31 年度毛利为6,492,762,000 CNY（报告期/时点: 2024-12-31; 口径: 年度; 单位: CNY），接口/字段 SEC EDGAR Company Facts.毛利 [^1]
- 营业收入（请求报告期：2024）：NIO Inc. 2024-12-31 年度营业收入为65,731,559,000 CNY（报告期/时点: 2024-12-31; 口径: 年度; 单位: CNY），接口/字段 SEC EDGAR Company Facts.营业收入 [^1]

## 参考来源
[^1]: SEC EDGAR Company Facts CIK0001736541 毛利. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/ (2025-04-08) [source_tier=primary]
[^2]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=06ec0187-0d4a-5692-8088-f591be777205 (2025-04-08) [source_tier=primary]
[^3]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=26826d5c-6ebd-5f09-a63c-79e8ba324379 (2025-04-08) [source_tier=primary]
[^4]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=3227f213-3fdc-5f75-b0bd-3305b715ceee (2025-04-08) [source_tier=primary]
[^5]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=44b3cfe5-f724-5d7b-9329-5b8a37eecdff (2025-04-08) [source_tier=primary]
[^6]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=5d5c6ee8-ed8a-5fb4-acc7-e5b0a8a269b7 (2025-04-08) [source_tier=primary]
[^7]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=649b1dcd-9f25-5319-bc4f-3c863d62be4f (2025-04-08) [source_tier=primary]
[^8]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=811628a2-b525-51d8-a0bd-b8b286621828 (2025-04-08) [source_tier=primary]
[^9]: nio-20241231x20f.htm. https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/nio-20241231x20f.htm#chunk=cc091dce-be50-5f95-adcf-502653481960 (2025-04-08) [source_tier=primary]
<!-- END 087 EMBEDDED REPORT -->

## 三分钟跑起来

```bash
python3 -m venv .venv
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pip install -e ".[dev]"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py
```

默认路径使用 deterministic fixture，不需要付费 provider 或 API key。

## 凭什么信它

报告把数值、对应 Evidence、引用闭合和成本账本放在同一个研究包；strict replay 用于复现已记录的轨迹，而不替代产物正确性检查。最终 NIO 包的数字、脚注和 provider 身份均由独立探针复核。

## 架构与边界

工作流由 Planner、Researcher、Extractor、Critic、Reporter 与 Evaluator 组成；研究子问题通过 LangGraph `Send()` 并行 fan-out。NodeContract、DecisionGate 与显式 DomainPack 约束边界。金融是唯一真实领域实现，不能据此宣称 harness 已通用可用。

## 25 个能力的实测状态

| Flag | Default | 087 outcome |
| --- | --- | --- |
| BRANCH_BUDGET_ENABLED | on | not tested in 087 A/B |
| CONFIG_FAIL_FAST_ENABLED | on | not tested in 087 A/B |
| CONTEXT_PACKER_ENABLED | on | promoted |
| CRITIC_ENABLED | on | not tested in 087 A/B |
| DECISION_WEAVING_ENABLED | on | promoted |
| DYNAMIC_CAPABILITY_ENABLED | on | not tested in 087 A/B |
| EXTRACTOR_ENABLED | on | not tested in 087 A/B |
| INJECTION_GUARD_ENABLED | off | not tested in 087 A/B |
| LLM_TOOL_SELECTION_ENABLED | off | not tested in 087 A/B |
| NUMERIC_CHECK_ENABLED | on | promoted |
| PRIOR_MEMORY_ENABLED | off | not tested in 087 A/B |
| PROCEDURAL_MEMORY_ENABLED | off | not tested in 087 A/B |
| PROGRESSIVE_DELIVERY_ENABLED | off | kept_off |
| RAG_ENABLED | off | not tested in 087 A/B |
| REFLECTION_ENABLED | off | not tested in 087 A/B |
| RERANK_ENABLED | on | not tested in 087 A/B |
| RERANK_FAIL_OPEN | on | not tested in 087 A/B |
| RESEARCH_LOOP_ENABLED | off | kept_off |
| RUN_MANIFEST_ENABLED | on | not tested in 087 A/B |
| SEMANTIC_JUDGE_ENABLED | on | promoted |
| SKILL_PACKS_ENABLED | off | kept_off |
| STRUCTURED_LOGGING_ENABLED | on | not tested in 087 A/B |
| STRUCTURED_OUTPUT_ENABLED | on | not tested in 087 A/B |
| TOOL_CONTRACT_ENABLED | on | not tested in 087 A/B |
| TRAJECTORY_RECORD_ENABLED | off | kept_off |

`promoted` 表示真实单开关 A/B 触发至少一项报告形态改善且没有形态劣化；`kept_off` 表示没有满足该规则。未测试项保持原默认值，不把“已接线”写成质量结论。

## 可审计性怎么实现的

每次运行保留 report、structured output、Evidence、manifest、ledger 与审计包。脚注映射不依赖 Evidence 当前顺序；外部工具经过超时、重试、预算与显式降级边界。

## 门禁与回归

唯一完整本地入口是 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py`。它覆盖 Settings 文档同步、领域边界、Ruff、prompt drift、完整单元测试、确定性 demo/eval smoke 与受跟踪文件不变检查。

## 它不做什么

- 不构成投资建议；分析师仍负责问题定义、来源许可、材料性、预测审批、发布和最终投资判断。
- 不把 strict replay 当成事实正确性的证明。
- 不在默认 CI、demo 或完整单测中要求付费 key。
- 不把当前金融领域 SUT 的验证外推为通用 domain-pack 能力。
