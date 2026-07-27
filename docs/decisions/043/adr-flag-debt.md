# ADR：默认关闭的内容开关归宿

所有下列开关均为 `content_affecting`，默认保持 `false`。本轮不把“已有代码路径”当作
转正证据；每项只有“验证转正”或“删除”两种归宿。

| Flag | 归宿 | 转正/删除的可验证条件 |
|---|---|---|
| `CONTEXT_PACKER_ENABLED` | 验证转正 | 至少四个 golden case（含组合开关）无质量门退化，且 evidence 顺序变化有比较报告。 |
| `DECISION_WEAVING_ENABLED` | 删除 | B6 LLM 工具决策闭环落地后，若仍无独立可测语义则删除。 |
| `INJECTION_GUARD_ENABLED` | 验证转正 | 注入 golden set 的 recall 与误杀率被版本化评测证明。 |
| `NUMERIC_CHECK_ENABLED` | 验证转正 | 真实/fixture 双层数值误差集与 false-positive 上限被记录。 |
| `PRIOR_MEMORY_ENABLED` | 验证转正 | snapshot follow-up 的可归因改善且无跨任务泄漏。 |
| `PROCEDURAL_MEMORY_ENABLED` | 删除 | 若 B1 run-scoped 隔离后没有独立的可复现收益，删除。 |
| `REFLECTION_ENABLED` | 验证转正 | 固定预算下相对 baseline 的质量改善与成本上限同时满足。 |
| `RESEARCH_LOOP_ENABLED` | 验证转正 | B1 后八并发 run 隔离及循环预算守卫均通过。 |
| `SEMANTIC_JUDGE_ENABLED` | 验证转正 | 真实 judge 预登记实验及人工抽样一致性达标。 |
| `SKILL_PACKS_ENABLED` | 删除 | 若 B6 的 capability schema 已覆盖其价值，删除该内容开关。 |

不得存在“已接线、未验证”的第三状态；任何转正都必须同步更新 `docs/evaluation.md` 与
版本化 baseline。
