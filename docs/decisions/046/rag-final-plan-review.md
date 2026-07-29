# 046 RAG 最终方案审阅修复

日期：2026-07-29

## 结论

`_collab/046_rag-plan-review/rag-final-plan.md` 的 96 条 plan_ref 计数与唯一性正确。审阅发现并修复了六处会使 047 无法按声明验收，或会错误宣称完成的计划问题。

1. B0 声明不改 `src/`，但 D5、费用登记与 B0-2 同时要求把单价写入 `llm_config.py`。现改为 B0 只记录当天探针事实，B4-2 才把该事实写入集中定价表。
2. I2 和 B6-11 用未提交工作树的 `git diff --stat tests/golden_output/` 证明关闭 RAG 的行为不变；提交后该检查恒为空。现改用已有的 `WorkflowCharacterizationTest`，它生成、归一化并逐字对拍 fixture workflow snapshot。
3. B4-10 没有定义 Qdrant 集成测试在默认 CI 中如何保持零出网。现要求以 `DEEPRESEARCH_QDRANT_URL` 显式启用，否则 skipped；本地 Docker profile 承担集成验证。
4. B5-7 的“本地、零付费”压测没有指定 embedding/rerank 实现。现明确使用 fixture providers 与本地 Qdrant。
5. B5-5 把不达标说成 `INCOMPLETE`，但台账只接受 PASS/FAIL/DEFERRED；现明确写为 FAIL，并禁止依据 test 结果调参或调整评测集。
6. 第 6 节错误地允许 DEFERRED 仍判 COMPLETE；现要求全部 96 条均 PASS，任何 FAIL/DEFERRED 都使全轮 INCOMPLETE。B6-12 的“真实”也改为符合项目对三层均非 fixture 的定义。

此外修正了 B5-4a 的 `rg` 正则，使其真正检查硬编码的 50/8，而非匹配带反斜杠和竖线的字面量。

本轮未实施 047 的 RAG 功能、未调用付费 provider、未做任何远端写。
