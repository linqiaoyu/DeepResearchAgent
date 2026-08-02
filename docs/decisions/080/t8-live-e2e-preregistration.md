# 080：T8 真实三层 E2E 预注册

## 授权与不可变实验设计

用户于 2026-08-02 明确授权本次 T8：单次最高 ¥15、全轮最高 ¥20。本文件所在
commit 先于任何带 `--allow-paid-api` 的调用；该调用之后不再重跑、调参或挑选结果。

冻结运行：`scripts/run_research_package.py --mode live --allow-paid-api`，主题为
“Alibaba 2024 annual report”，`as_of=2026-07-01`，深度 1，真实 LLM、Tavily
搜索、DashScope embedding/rerank RAG，结构化数据 provider 为
`sec_companyfacts`，SQLite 语料库为 `data/runtime/047-assets.db`，索引版本为
`finance_v1-43f11085-heading_page_first_1024_256`。该 as-of 晚于所选 20-F 的
`published_at`。

## 假设、测量与决策规则

假设：一次有界真实运行会交付非空 `report.md`，且 manifest 完整地记录实际三层
provider、传入的索引版本与成本；`actual_realness` 必须为 `real`。

验收测量严格采用 T8 任务卡：报告非空、`actual_realness=real`、
`retrieval_index_version` 等于上述版本、RAG 账本至少一条 embedding 或 rerank
记录且总成本不超过 ¥15、报告包含 `audit_citation_closure`。运行结束后执行完整 gate。

预算分配：workflow LLM ¥3，RAG ¥12，合计单次 ¥15；本轮总熔断 ¥20。任何一个
provider 三次重试耗尽、任一预算/全轮熔断触发、Qdrant 不可达或报告交付失败，立即停止
本项，不作第二次付费调用。若本次失败，修复后的新实验需要新的明确授权。

## 运行前零费用检查

本地 `.env` 的必需凭据均存在（未输出其值），`data/runtime/047-assets.db` 存在，且
Qdrant collection 的只读 HTTP 预检返回 200。正确设置 `PYTHONPATH=src` 后，live
脚本在未给 `--allow-paid-api` 时唯一失败原因为该显式付费确认，证明配置 fail-fast 通过。
一次遗漏 `PYTHONPATH=src` 的命令构造失败已保留在 `_collab/080-t8-live-e2e/evidence/`，
不计作产品或实验失败。
