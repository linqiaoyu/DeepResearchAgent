# 049：空 RAG 索引的显式降级

## Decision

`rag_search` 的统一调用协议为
`search(*, query: str, as_of: str, context: RunToolContext | None = None) -> dict`。
能力注册会在装配时检查三个命名参数，避免不兼容实现进入默认引擎。

## H1 root cause and resolution

默认的 `EmptyRagSearchTool` 缺少生产调用始终传入的 `context` 参数，因此启用 RAG
的每个研究分支都会抛出 `TypeError`。空索引现在把
`rag_search/not_found/empty_result` 追加到运行上下文；交付节点同步该事件到 state
metadata，因而 manifest 可见。其 trace 保持紧凑的 `empty_index` 映射，因为预索引状态
没有 `RetrievalTrace` 所要求的后端计数和索引版本。

## Verification excerpt

- RAG demo: `exit=0`; report non-empty; manifest rag_search degradation count: `1`.
- `tests.unit.test_rag_capability`: 4 tests, `OK`.
- Full gate: `ci_env_match=true`; completed successfully.
- Mutation: removing `EmptyRagSearchTool.search(..., context=...)` made the protocol guard
  fail with `EmptyRagSearchTool violates the search protocol: missing context`.
