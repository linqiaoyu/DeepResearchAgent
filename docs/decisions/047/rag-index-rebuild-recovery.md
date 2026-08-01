# RAG 索引重建的故障恢复边界

## 决定

Qdrant 是从权威关系存储派生出的索引。一个 chunk 只有在 embedding 返回完整向量且
Qdrant `upsert` 成功之后，才能写入该 index version 的 checkpoint；checkpoint 中的
chunk ID 是本重建流程的 index-ready 状态。失败中的或未提交的批次不得登记，因此重启时
只跳过已确认写入的批次。

## 证据

`tests.unit.test_rag_index_rebuild_recovery` 离线注入四种故障：embedding 断网、429、
Qdrant 超时和第二批次超时。前三种都显式抛出并留下空 checkpoint；部分批次失败时只有
首批两个 ID 被登记，恢复运行仅提交余下两个 ID。

M4 临时删除 `scripts/rebuild_rag_index.py` 中成功 `upsert` 后的 `_save_checkpoint(...)`
调用，部分批次恢复测试随即失败。原始输出保存在
`artifacts/047/mutations/b4_m4_checkpoint_after_upsert_guard.log`；该保护已恢复。
