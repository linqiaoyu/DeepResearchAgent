# 019-C 真实模式研究包验收清单

版本：截至 019-C / 来源轮次

冻结日期：2026-07-25。019-C 只能按本清单收紧判定，不得因真实结果不理想而放宽。A8 的 stub 结果只作为结构下限，不代表真实模型质量。

## 报告

- [x] 必须包含“摘要、关键发现、详细分析、风险与限制、未验证假设、参考来源”六个一级业务章节；缺失数必须为 0。A8：`0`。
- [x] “关键发现”和“详细分析”中的结论项目必须 100% 至少绑定一个 Evidence 脚注。A8：`6/6 = 1.000`。
- [x] 所有已出现脚注必须可经 `report_footnote_evidence` 解析为包内 Evidence；未闭合数必须为 0。A8：`0`。
- [x] `TODO`、`TBD`、`placeholder`、`当前没有足够证据` 命中总数必须为 0。A8：`0`。
- [x] 摘要必须明确数据/证据边界和不得外推的质量边界；A8 明确写出“本地 fixture”及“不能外推为真实模型质量”。
- [ ] 019-C 额外质量门槛：摘要、关键发现和详细分析不得只是同一句话重复；若任意两节的结论集合完全相同则不通过。详细分析中的每一项还必须与至少一条关键发现共享 `entity + normalized_metric`，或显式引用关键发现的 Evidence 脚注；不可追溯的事实只能进入单独的“补充事实”一级章节。详细分析不可追溯项数必须为 `0`。A8：不通过，关键发现与详细分析三条完全重复，且未执行关联性分类。

说明：风险说明、方法限制和“未验证假设为空”的状态句不当作事实结论，允许无脚注；风险节若出现具体公司事实、数字、日期或因果判断，则必须绑定 Evidence。

## 结构化对象

- [x] ComparisonTable 必须至少有 1 条 MetricRow；每行的 `entity/metric/normalized_metric/period/scope/value/unit/confidence/evidence_ids` 全部非空。A8：`4/4` 完整。
- [x] EventTimeline 必须至少有 1 条 Event；每行的 `occurred_at/event/source/thesis_impact/evidence_ids` 全部非空。A8：`6/6` 完整。
- [x] RiskMatrix 必须至少有 1 条 RiskItem；每行的 `risk/likelihood/impact/verification_status` 全部非空，无证据项必须明确为 `unverified`。A8：`1/1` 完整。
- [x] 四类对象 `MetricRow / ComparisonTable / EventTimeline / RiskMatrix` 均非空；A8：分别为 `4 / 1 / 6 / 1`。
- [x] 每条 MetricRow 的口径字段 `period` 和 `scope` 必须非空。A8：`4/4`。
- [ ] 019-C 数字展示门槛：面向读者的报告正文不得用未解释的科学计数法展示人民币；结构化原始值可保留数值类型，但报告应转为亿元等可读单位。A8：不通过，出现 `3.62013e+11元`。

## 审计包

- [x] 引用闭合必须为 100%，即已引用 Evidence 的缺失数为 0，导出结果为 `citation_closure=ok`。A8：`ok`。
- [x] manifest 必须至少包含 `run_id/started_at/ended_at/mode/model_strings/prompt_hashes/config_hash/flags/decision_summary/dependency_versions` 十项。A8：`10/10`。
- [x] 封面必须出现“本报告由自动化系统生成，不构成投资建议”，并披露成本是估算而非 provider 最终账单。A8：存在。
- [x] Evidence 对外摘录不得超过 1,000 字符，并必须携带完整正文 SHA-256 与截断标识；该项由 A6 守卫测试检查。
- [ ] 019-C 血统门槛：所有真实 LLM 调用必须在 ledger 和 trajectory 两处均可按 role、model、tokens、cost、latency 对账；任一调用只存在单侧即不通过。A8 仅证明 stub 调用可双写。

## 快照与变更追踪

- [x] ResearchSnapshot 必须至少有 1 条 claim、非空 `manifest_ref`，并内嵌三类 structured objects。A8：`6` 条 claim，后两项均为 true。
- [x] 比较器 schema 必须保留六类变更：`added_claim / disappeared_claim / numeric_change / evidence_replacement / confidence_change / scope_change`。A8 前置检查：`6/6`。
- [ ] 019-C 必须用同题的前后两个真实快照实际执行一次 diff；每条变化须包含 `change_type/materiality/key/display_key/old_as_of/new_as_of/detail`。A8 只有单快照，故此项尚不能通过。

## 人工可读性评语（A8）

1. 摘要清楚标明“本地 fixture”和“不能外推为真实模型质量”，读者不容易把本次冒烟误认为真实投研结论；这条边界应原样保留到真实模式。
2. 关键发现和详细分析逐字重复同三条，缺少“数字意味着什么、扩张时间冲突如何影响判断”的分析层；真实报告若仍如此，结构虽完整但不能称为可直接给分析师使用。
3. 同一营收既以 `3620.13 亿元` 又以 `3.62013e+11元` 展示，数学上相容但阅读负担明显；真实报告需要统一读者单位，并把原始元口径留在结构化表或审计层。

## A8 结构下限结论

A8 通过所有可在单次 stub 包上机械验证的结构门槛：章节 6/6、结论引用 100%、脚注缺失 0、占位符 0、四类结构化对象非空、manifest 10/10、封面免责存在、快照 claims 6。它未通过两项预先冻结的真实质量门槛（结论重复、科学计数法可读性），也无法验证双真实快照 diff 和真实调用双账一致性。这些结果是 019-C 的否决条件，不得在付费后改写阈值。

机械命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019a_spending_eligibility_audit/run_a9_check.py`
