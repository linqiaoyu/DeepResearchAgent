# ADR 047: RAG MVP storage and retrieval boundary

## Status

INCOMPLETE. This decision records the implemented boundaries. It does not turn
the separate retrieval-quality failure or outstanding service exercises into
accepted results.

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
- `RetrievalFilter` remains domain-neutral. A `RetrievalDomain` returns only
  neutral document-type, entity-id, and period-label values; the finance pack
  owns its query interpretation, while `rag/search.py` only merges and passes
  those values to backends.
- Embedding and reranking have independent provider HTTP adapters but reserve
  and settle through the existing LLM ledger and run budget. Model endpoints,
  batch limits, and price sources must be explicitly configured.
- Qdrant was selected over pgvector in part to demonstrate vector-database
  operations in this project. That portfolio objective is a real motivation;
  it is not presented as a technical necessity. The resulting point-to-chunk
  reconciliation and derived-index recovery work remains part of the cost.
- The RAG implementation adds no runtime dependency: it uses the existing
  pinned `httpx==0.28.1` (BSD-3-Clause) REST client and
  `psycopg[binary]==3.3.4` (LGPL-3.0-or-later) PostgreSQL adapter. `pypdf`
  remains pinned at `6.14.2` (BSD-3-Clause); `pdfplumber==0.11.10` remains a
  development-only dependency (MIT), not a runtime dependency.

## Rejected options

- `pgvector` is not selected: the user decision for this round is Qdrant, and
  combining vector search with the relational authority would obscure the
  independent reconciliation and recovery boundary.
- `pg_bigm` is not selected: it would introduce a PostgreSQL extension and
  make the default offline path unavailable. The selected lexical path is
  application-layer CJK tokenization over the authoritative store.
- Qdrant sparse is not selected: a second sparse index would duplicate lexical
  state and make its authority/rebuild contract larger without measured gain.
- OpenAI embedding is not selected because cross-border latency is an explicit
  operational concern. Local BGE-M3 is not selected because its model/runtime
  footprint is outside this MVP's dependency budget. The selected embedding
  provider is DashScope `text-embedding-v4`, using the shared ledger and the
  configured domestic provider path.

## Non-decisions and blockers

- The user confirmed the immutable 60-document raw corpus and 60-question
  span-labelled retrieval set as manual work. Validation records 22,953 active
  chunks, 65 labels, zero unresolved labels, and corpus fingerprint
  `43f1108577d5c3a56f9daeb1d9c942b985a73759fce7d11e374831c67c0badb5`.
- The configured Qdrant service contains 22,953 payload-only points for the
  same number of authoritative chunks. This establishes the derived-index
  reconciliation boundary, not the retrieval-quality gate.
- A pinned, loopback-only `qdrant` Docker Compose profile and an explicit-URL
  integration test are available for local verification. Docker was unavailable
  in this round, so that profile has not been executed.
- PostgreSQL integration is not claimed: `DEEPRESEARCH_PG_DSN` was absent, so
  its contract test was skipped by design.
- A full three-provider workflow is still not accepted: the existing live run
  did not produce an end-to-end RAG-supported report and must not be called a
  successful three-layer E2E result. Synthetic content must not substitute for
  the confirmed corpus or labels.
- Real DashScope embedding and rerank calls were preregistered and charged
  through the shared ledger. Account-specific rate-limit and maximum-candidate
  limits remain unverified rather than inferred from those calls.

## Rerank limitation

Rerank is default-enabled in configuration, but its standalone retrieval gain
was not measured in this round. Any future whole-pipeline retrieval improvement
must not be attributed to rerank alone.
