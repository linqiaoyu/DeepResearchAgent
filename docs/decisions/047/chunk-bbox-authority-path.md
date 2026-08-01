# Chunk bbox authority path

The authoritative `chunk` record owns any layout coordinates associated with a
retrieval chunk. Migration `003_chunk_bbox_index.sql` adds a JSONB
`bbox_index_json` column for Postgres; SQLite uses the same JSON field with an
idempotent local schema upgrade.

Both storage adapters hydrate this field into `ResolvedChunk`, and both lexical
and dense backend adaptation passes it to `SearchChunk`. This makes the
existing RAG candidate-to-`Source` adapter receive original layout coordinates
without reading them from Qdrant payloads or fabricating a box.

The verified `finance_v1` corpus is HTML-only, and its chunks correctly retain
an empty bbox index. PDF support is therefore verified separately, without
inventing coordinates for that corpus: `pdfplumber` extracts word-level boxes
from two real public PDF probes (3/3 and 7/7 chunks carried boxes), while the
cross-layer guard covers PDF words → authoritative SQLite chunk → lexical RAG
candidate → `Source` URL with `#chunk` and bbox → Extractor-produced
`Evidence.retrieval_ref` → Critic. The guard also fails when the
`bbox_index=chunk.bbox_index` write in `ingest.py` is removed.

This is sufficient for B6-4. It does not convert the HTML corpus into a PDF
corpus or claim that a PDF-derived box has been observed for an HTML source.
