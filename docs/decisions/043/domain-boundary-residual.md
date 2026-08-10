# 043：金融字面量残留清单

边界守卫当前值为 `literal_files=5`、`literal_hits=10`。以下残留均为受约束的通用契约、
评测资产或核心 prompt；任何新增命中仍会被 allowlist 棘轮拒绝。

R112 更新了本表两处。其一是修正：正文此前写 `literal_hits=9` 且 reporter.py 记 5 命中，
而守卫实测为 8 与 4——本清单本身漂移过，未被任何检查发现。其二是扩容：棘轮此前只扫描
`src/`，`prompts/` 是完全的盲区，扩展扫描后立刻暴露两个核心 prompt 各 1 行。

| 文件 | 命中 | 保留理由 | 移除条件 |
|---|---:|---|---|
| `src/deepresearch_agent/agents/reporter.py` | 4 | 报告器的中文可读格式化与证据页码显示；指标判定、单位换算和引用策略已经由 DomainPack 注入。 | 报告呈现层完成 locale/domain renderer 拆分时。 |
| `src/deepresearch_agent/evaluation/gold_audit.py` | 3 | 版本化 golden-set 的审计断言，不能在不新建评测版本的情况下改写。 | 发布新的 golden-set 版本并同步评测契约时。 |
| `src/deepresearch_agent/schemas.py` | 1 | `SymbolInfo.exchange` 的历史序列化默认值；它是兼容数据契约，不参与领域判断。 | 具备 schema 版本迁移和旧轨迹迁移测试时。 |
| `prompts/planner.md` | 1 | 计划器 prompt 直接列举 `financial_indicators` 的可选指标名。这是真实的领域泄漏，不是格式化：它把一个领域的指标词表写进了核心 prompt。 | DomainPack 能贡献 prompt 片段时——即 prompt 具备与代码同样的注入点。 |
| `prompts/reporter.md` | 1 | 报告器 prompt 规定 RMB 金额按 元/万元/亿元 渲染。同上，属于核心 prompt 里的领域约定。 | 同 `prompts/planner.md`。 |

本清单不将上述残留解释为领域迁移完成；它只记录为什么在最小修复边界内不应进行破坏性
迁移。两个 prompt 条目尤其不应被读成"已解决"：目前没有任何机制让第二个领域替换它们，
棘轮锁住了这笔债，没有偿还它。
