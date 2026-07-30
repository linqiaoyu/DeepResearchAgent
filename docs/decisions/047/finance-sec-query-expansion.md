# Finance SEC query expansion

The approved corpus contains public English SEC 20-F filings while the finance
product accepts Chinese issuer names. `FinanceDomainPack` therefore appends a
public English issuer alias to a retrieval request before either lexical or
dense retrieval. Generic RAG code receives only the expanded string through
the injected `RetrievalDomain`; it contains no finance vocabulary.

The authoritative `chunk` record now persists a stable `entity_id`, derived
from the frozen corpus filename prefix during ingestion. `period_label` is
derived from the already-authoritative `effective_date`. SQLite and Postgres
carry the entity field; Qdrant receives only the two filter fields, never chunk
text. The lexical and dense backends apply both entity and period constraints.
`document_type` remains unsupported and is still rejected fail-closed.

The existing derived index was backfilled by stable point ID: 22,953 points
across 60 issuer/year groups. This payload-only operation did not invoke an
embedding or rerank provider. It does not relax as-of, URL, document-version,
character-range, extraction, or evidence-chain guards.

The aliases are public issuer vocabulary, not writes to the frozen questions,
labels, split, or relevance values. The completed test result predates this
code change and remains the recorded negative B5-5 experiment. A new paid
quality experiment requires separate authorization and preregistration.
