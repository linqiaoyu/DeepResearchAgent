# 021：审计缺口阶段 0--4 边界交付

## 决策

- 补充 020-F 冻结 characterization 的分类归因；所有已审查变更均可归因到 F1--F4，
  不以派生评估数字变化宣称质量提升。
- 巨潮公告适配器以证券代码显式区分沪市与深市 A 股；北交所、港股、基金、债券及
  未识别代码在网络请求前 fail closed。
- 历史 chaos CI 失败经至少 50 次完整环境和 20 次 CPU 竞争复测均未复现；没有足够
  机械证据归因到 020-F，结论保持“无法归因”。

## 不利事实与边界

- 提供的 real-mode 轨迹仅覆盖 Extractor，缺少完整 engine strict replay 所需的
  request、plan、节点转换及决策信息。real-mode 严格回放仍为 INCOMPLETE；没有
  引入 strategy 宽松匹配，也没有伪造缺失缓存项。
- 记忆、其余骨架能力、能力状态表、默认可见性及 README/静态站阶段未在本轮边界
  交付中实施。

## 验证

- 本地 CI 等价闸门通过。
- 巨潮沪市真实调用在 3 次请求内取得并解码贵州茅台 2025 年年度报告。
- `tests.unit.test_disclosure_source`：6 tests, OK；相关 Ruff 检查通过。
