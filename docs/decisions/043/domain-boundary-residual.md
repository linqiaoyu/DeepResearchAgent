# 043：金融字面量残留清单

边界守卫当前值为 `literal_files=3`、`literal_hits=9`。以下残留均为受约束的通用契约或
评测资产，不承载金融工作流决策；任何新增命中仍会被 allowlist 棘轮拒绝。

| 文件 | 命中 | 保留理由 | 移除条件 |
|---|---:|---|---|
| `src/deepresearch_agent/agents/reporter.py` | 5 | 报告器的中文可读格式化与证据页码显示；指标判定、单位换算和引用策略已经由 DomainPack 注入。 | 报告呈现层完成 locale/domain renderer 拆分时。 |
| `src/deepresearch_agent/evaluation/gold_audit.py` | 3 | 版本化 golden-set 的审计断言，不能在不新建评测版本的情况下改写。 | 发布新的 golden-set 版本并同步评测契约时。 |
| `src/deepresearch_agent/schemas.py` | 1 | `SymbolInfo.exchange` 的历史序列化默认值；它是兼容数据契约，不参与领域判断。 | 具备 schema 版本迁移和旧轨迹迁移测试时。 |

本清单不将上述残留解释为领域迁移完成；它只记录为什么在 043 的最小修复边界内不应进行
破坏性迁移。
