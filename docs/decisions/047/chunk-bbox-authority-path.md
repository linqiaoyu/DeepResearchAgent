# Chunk bbox authority path

The authoritative `chunk` record owns any layout coordinates associated with a
retrieval chunk. Migration `003_chunk_bbox_index.sql` adds a JSONB
`bbox_index_json` column for Postgres; SQLite uses the same JSON field with an
idempotent local schema upgrade.

Both storage adapters hydrate this field into `ResolvedChunk`, and both lexical
and dense backend adaptation passes it to `SearchChunk`. This makes the
existing RAG candidate-to-`Source` adapter receive original layout coordinates
without reading them from Qdrant payloads or fabricating a box.

The verified `finance_v1` corpus is HTML-only. Its chunks correctly retain an
empty bbox index. Consequently this persistence repair is not evidence that
the plan-required real-PDF bbox extraction probe has passed; B6-4 remains
DEFERRED until that distinct evidence exists.
