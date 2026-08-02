# 080：T8 真实三层 E2E 结果

## 结论

**PASS。** 预注册 commit `caa2ffe` 后只执行了一次付费运行，已满足 048 任务卡 T8
的全部运行验收。没有调参或第二次调用。

## 不可变记录

- 时间：2026-08-02 14:27:23–14:30:31 UTC（约 188 秒）。
- 代码 commit：`caa2ffe`（运行前预注册）。
- workflow research/run id：`0f2c7994-d31a-4833-86e7-90f51455c6d4`。
- RAG ledger run id：`rag-e2e-6c8cd28f-a298-435c-b0fc-4cbb27592375`。
- 配置：Alibaba 2024 annual report；`as_of=2026-07-01`；depth 1；live LLM、
  Tavily search、SEC Company Facts structured data、DashScope embedding/rerank；
  `data/runtime/047-assets.db`；
  `finance_v1-43f11085-heading_page_first_1024_256`。
- 结果：`report.md` 非空，`actual_realness=real`，索引版本与传入值相同，
  `audit_citation_closure=ok`。
- 成本：workflow manifest `cost_cny_total=0.03548236`；RAG ledger
  `0.092826`；合计 `0.12830836` CNY，低于单次 ¥15 和全轮 ¥20。

任务卡允许 RAG 账本 run id 与真实 research id 显式并列；本次选择该路径。交付报告的
“Live RAG cost reconciliation”段保存二者及 RAG 成本，因此不存在合成 run id 冒充研究
run id 的歧义。`scripts/run_research_package.py` 已在本次运行前使用公开的
`engine.close()`，无需额外代码修复。

## 验证

`_collab/080-t8-live-e2e/evidence/acceptance.log` 保存各项原始命令输出；其中 RAG
embedding/rerank 账本记录为 6。完整门禁命令
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py` 在本次运行后退出 0，
原始输出保存在 `_collab/080-t8-live-e2e/evidence/gate_080.log`。
