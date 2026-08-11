# R133 — RAG ingestion and derived-index contract

## Verdict

PASS. H09 is complete. `rag` remains `wired` until H10 proves retrieval-layer
composition, degradation, and accounting required for H2 readiness.

## Defect repaired

The relational store already withheld chunks whose disclosure date was unknown,
but `QdrantIndex.upsert` independently used
`published_at or effective_date`. Worse, the production rebuild command did not
pass the relational `published_at`, so every rebuilt vector point silently used
the report-period end as though it were the disclosure date.

`IndexedChunk` now requires document version, canonical source URL, disclosure
date provenance, and index version. The rebuild command supplies these from the
authoritative relational row. An empty disclosure date or provenance is
withheld before any Qdrant request; it is never replaced. A chunk-level index
version that differs from the upsert configuration is rejected before HTTP.
Qdrant payloads retain the four provenance fields without storing source text.

## Idempotency

Relational re-ingest of the same manifest adds and removes zero chunks. Vector
point ids remain deterministic over chunk/model/chunker, so repeating an upsert
targets the same id. Index-version mismatch remains fail-closed at both write
and query collection validation.

## Verification before complete gate

- RAG ingestion checker: PASS, 7 cases; provenance 1.0, repeated additions and
  removals 0, undated visible 0, unknown vector writes 0, stable point id 1.0.
- RAG ingest/Qdrant/rebuild recovery: 24 tests pass after updating real
  production-shaped rebuild fixtures with source and disclosure fields.
- Ruff passes.
- No provider, network, paid, or remote Git write occurred.

## Falsification

The production eligibility filter was temporarily changed to pass every vector
chunk, including the undated one. The real checker exited 1 with
`rag_ingestion_self_test=FAIL production probe is dirty`. Restoring the filter
returned unknown vector writes to zero. Six checker data mutations separately
reject missing provenance, non-idempotent ingest, visible undated data,
period-end fallback, unstable point ids, and version mismatch acceptance.
