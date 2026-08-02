# 060：T8 账本对账修复与门禁复核

## 决策

修复 `scripts/run_research_package.py` 在真实运行完成后写出报告时读取错误
聚合字段的缺陷。`LLMClient.aggregate_run()` 的合同字段是
`total_cost_cny`，不是 `cost_cny_total`。

将对账逻辑抽为 `_append_live_rag_cost_reconciliation()`，在写入结果前验证
RAG ledger run id、ledger 类型、workflow research id 与 metadata，并把同一份
聚合摘要同时写入 state metadata 和 Markdown 报告。

## 依据

Round 059 的真实 mixed 运行已完成 workflow，但输出收尾阶段抛出
`KeyError: 'cost_cny_total'`，因此没有写出报告、structured 输出或审计包。该轮的
provider 结果仍按 INCOMPLETE 保留；本轮不重跑 provider。

新增集成测试以真实 `LLMClient` 的 JSONL 聚合结果验证报告文字、两个 run id 与
`state.metadata["rag_cost_summary"]["total_cost_cny"]`。临时把实现变异回
`cost_cny_total` 后，该测试以 `KeyError` 失败；原始输出保存在
`_collab/060-fix-t8-ledger-reconciliation/evidence/mutation_wrong_aggregate_key.log`。

## 相邻门禁修复

首次完整 gate 失败于 existing `wealth_context_packer` characterization：一个 UUID
中 `[REDACTED_PHONE]` 后仍保留一个尾部十六进制字符，旧的 `REDACTED_UUID_RE`
只匹配脱敏标记结尾，留下了该字符。扩展正则以同时吞掉标记前后的十六进制片段，且只在
字符串结束或非词字符前结束匹配。新增单测覆盖这一精确形状；回退至旧正则时测试失败，
原始输出保存在
`_collab/060-fix-t8-ledger-reconciliation/evidence/mutation_redacted_uuid_suffix.log`。

没有更新任何 golden snapshot、评测集或判分合同。

## 验证

- 初次完整门禁：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py`，
  721 tests、1 failure、4 skipped；失败原始输出保存在
  `_collab/060-fix-t8-ledger-reconciliation/evidence/full_gate.log`。
- 修复后完整门禁：同一命令，722 tests、OK、4 skipped；原始输出保存在
  `_collab/060-fix-t8-ledger-reconciliation/evidence/full_gate_after_uuid_fix.log`。
- 本轮未调用真实 LLM、检索或数据 provider，成本为 ¥0。

## 后续

只有在收到新的、明确的付费授权后，才可用修复后的收尾逻辑重跑 T8 真实 E2E；届时必须
新建 preregistration，并将运行如实判定为 real 或 mixed。
