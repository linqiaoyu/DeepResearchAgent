# R134 — bounded hybrid retrieval H2

## Verdict

PASS. H10 is complete and `rag` is H2-ready. This is a Harness mechanism
verdict, not evidence that RAG improves the finance product.

## Retrieval closure

The production composition root provides real BM25 lexical retrieval, real
Qdrant dense retrieval with DashScope embeddings, and real DashScope reranking.
The live backend refuses startup when any required provider, collection, or
index-version configuration is missing; the explicitly named pre-index fixture
remains available but cannot be selected by omission.

The H2 probe executes lexical, dense, and rerank layers using recorded boundary
responses. Rerank timeout preserves the fused candidates in fail-open mode and
returns an explicit empty degradation in fail-closed mode. Every successful
recorded embedding and rerank provider request creates one shared-ledger row and
one retrieval trajectory event; the overall search creates its own redacted
`rag_search` tool-call trace.

The R133 ingestion contract is carried into the final RAG proof: indexed chunk
provenance is 1.0 and documents with unknown disclosure date visible at any
`as_of` remain zero.

## Boundary

No live provider, network, paid, or remote Git write was used. Recorded HTTP
responses test the production provider adapters and accounting path without
claiming live fidelity or reader-visible financial benefit.

## Falsification

The production rerank fail-open branch was temporarily changed to discard its
candidates. The gate-wired production probe exited 1 with
`rag_retrieval_self_test=FAIL production probe is dirty`. Restoring the branch
returned all ten metrics to their contracted values. Six output mutations also
reject a missing layer, silent configuration, either rerank-direction error,
missing cost rows, and missing provider trajectory events.
