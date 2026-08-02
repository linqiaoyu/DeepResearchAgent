# 050：RAG manifest 可观测性

manifest 现在发射所有三项 RAG 开关，记录启用 RAG 时的索引版本，并把 `[rag_search]`
与 web 搜索计数分开。RAG service fidelity 由实际 lexical、dense 和启用的 reranker
后端聚合。四个 characterization snapshot 仅增加这些 manifest 字段，故独立提交。

验证：flag 分类双向守卫、索引版本 `vT2`、usage 分类、fidelity 聚合均通过；删除
`RAG_ENABLED` 快照写侧会使守卫失败；完整 gate 通过。
