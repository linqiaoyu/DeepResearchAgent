# RAG rerank 降级的严格回放

## 决定

严格回放 RAG 时，trajectory 继续只记录 query hash、截至日、index version、候选 ID、
rerank 状态和降级原因，不记录 chunk 正文。调用方必须显式传入同次运行可审计的本地
SQLite 权威快照；`ReplayRagSearch` 从该快照按记录顺序水合候选，并且不调用 embedding
或 rerank provider。

## 证据

`tests.integration.test_rag_degraded_replay` 先录制一个 `rerank_status=degraded` 的
fail-open 工作流，再用相同 trajectory 和 SQLite 快照执行 strict replay。没有快照时
返回 cache miss；有快照时报告逐字复现，且记录的 Top-N candidate ID 顺序保持不变。
