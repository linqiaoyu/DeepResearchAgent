# ADR 047: RAG MVP storage and retrieval boundary

## Status

INCOMPLETE. This decision records implemented boundaries and the external
preconditions that prevented end-to-end acceptance in this round.

## Decision

- SQLite remains the default offline adapter. PostgreSQL is the authoritative
  relational adapter when `DEEPRESEARCH_STORAGE_BACKEND=postgres` and
  `DEEPRESEARCH_PG_DSN` are explicitly configured; its schema is versioned in
  `migrations/` and `docs/postgres_schema.sql` is generated from those files.
- Local corpus ingestion accepts only manifest-listed PDF, HTML, and TXT files.
  Document identity is URL-stable; content-hash changes create a new version
  and supersede prior chunks. No crawler, upload path, private corpus, or ACL
  system was added.
- `rag_search` is conditionally registered and fails safely with an empty-index
  result until real lexical and vector backends are configured. It does not
  create Evidence directly.
- Embedding and reranking have independent provider HTTP adapters but reserve
  and settle through the existing LLM ledger and run budget. Model endpoints,
  batch limits, and price sources must be explicitly configured.

## Non-decisions and blockers

- The configured Qdrant service was reachable and an empty collection was
  created with the expected vector dimension and cosine distance. This proves
  collection provisioning only: no source chunks, embeddings, or points were
  uploaded, and no search integration has been accepted.
- PostgreSQL integration is not claimed: `DEEPRESEARCH_PG_DSN` was absent, so
  its contract test was skipped by design.
- No real corpus, sixty-question human-labelled retrieval set, or real
  three-layer end-to-end run was created. Synthetic content must not substitute
  for these assets.
- The DashScope API key existed, but the workspace-specific embedding and
  rerank endpoints and console-confirmed pricing were absent. No paid probe was
  sent and no price was invented.

## Rerank limitation

Rerank is default-enabled in configuration, but its standalone retrieval gain
was not measured in this round. Any future whole-pipeline retrieval improvement
must not be attributed to rerank alone.
