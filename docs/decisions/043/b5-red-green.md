# B5 真 PDF fixture：首次红→绿归因

首次将真 PDF bbox 指标接入 `EvaluationResult` 后，完整门禁如预期变红；失败不是解析或
fixture 回退，而是两个 characterization snapshot 缺少新增的 display-only 字段。

原始关键失败输出：

```text
Ran 576 tests
FAIL: test_snapshot_run
finance_structured.json: missing `bbox_resolution_rate: null`
finance_structured.json: missing `bbox_resolution_reason: "no_paged_numeric_evidence"`
wealth_research.json: missing `bbox_resolution_rate: null`
wealth_research.json: missing `bbox_resolution_reason: "no_paged_numeric_evidence"`
```

归因与修复：

1. 字段来自新的 `EvaluationResult` 契约，是 display-only，不参与评分门禁。
2. 按原有默认 topic 重跑 snapshot 生成器，逐 hunk 确认只新增上述字段。
3. snapshot 变更独立提交为 `93f5eda test(snapshot): record bbox metric contract`。
4. 随后完整 `scripts/gate.py` exit 0；受管 fixture 由 gate 中的 `--check` 验证。

本记录保留预期失败及其唯一归因；没有通过回退 fixture、降低断言或修改 golden truth
消化失败。
