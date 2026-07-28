# 044 N0：年度报告与证券实体精确选择

## 决定

落实审计 M1 与 B1 的最小闭环。证券解析只接受唯一精确的六位代码或规范名称；部分名称和重复规范名称均返回 `None`，由调用方降级而非首命中。财务指标请求从 `StructuredDataRequest.periods` 取得唯一财年，并将其作为 `report_year` 传入披露源。

CNINFO 在存在 `report_year` 时请求完整候选页，随后仅接受标题年份精确匹配的唯一完整年度报告。零个或多个候选均返回空结果，绝不按 provider 顺序选择。年份标题规则保留在 finance DomainPack，工具核心不新增金融判断。

## 证据

- 100 次不同公告顺序下，2024 请求始终只返回 `贵州茅台2024年年度报告`。
- 删除标题年份相等判断的变异测试失败，错误地返回 2025 年报告。
- 完整 gate 通过。

## 后续状态

本轮随后完成了答案完成度、门禁事实源、并发预算、AKShare 超时隔离、ledger 增量索引、
round-status 机器断言、计划台账闭环、窄 capability protocol、ResearchOne 显式依赖切面，以及
NullDomainPack 的确定性全流程验证。核心源码不再含有硬编码的 finance pack 加载；兼容构造
仅解析 Settings 所选 pack。该结果消除了 finance 默认回退，但不宣称已经完成第二个真实
domain-pack 的产品化抽取。
