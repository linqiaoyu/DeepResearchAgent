# 研究快照与变更追踪

`ResearchSnapshot` 是面向投研跟踪工作的业务产物，与
`tests/golden_output/` 中用于回归测试的 characterization 快照相互独立。它保存研究问题、
截止日、按 `entity / metric / period / scope` 四键归一的论点、结构化对象、
run manifest 引用和生成时的开关快照。

`scripts/diff_snapshots.py` 在比较前先执行 manifest 可比性判定。内容影响型开关、
模型串、prompt hash 或 as-of 不同时，报告会显式警告“部分差异可能来自系统而非世界”，
并列出跨越项；警告不会隐去仍可供人工复核的业务差异。

## 变更分类

- 新增论点与消失论点：四键与论点身份仅出现在一侧。
- 数值变化：四键完全相同，但 value 或 unit 变化。
- 证据更替：论点键保持不变，支撑来源发生变化。
- 置信度变化：论点键保持不变，确定性置信度发生变化。
- 口径变化：entity、metric、period 相同但 scope 改变。它单独分类，绝不同时记作数值变化。

## 重大性规则

规则由 `MaterialityRules` 显式配置，不调用 LLM：

- 数值相对变化大于或等于 `numeric_relative_threshold` 时为 `material`，默认阈值 10%；
- 置信度绝对变化大于或等于 `confidence_absolute_threshold` 时为 `material`，
  默认阈值 0.10；
- 口径变化默认为 `material`；
- 方向为 positive 或 negative 的论点新增或消失默认为 `material`；
- 其余变化为 `minor`。

阈值用于排序复核优先级，不替代分析师对业务重要性、口径合理性和证据质量的判断。
fixture 派生的双期演示会在快照和报告顶部标记为“演示用构造数据”，不得解释为真实市场更新。
