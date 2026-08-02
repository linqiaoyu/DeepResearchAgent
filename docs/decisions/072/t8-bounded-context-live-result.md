# T8 bounded-context live result

## Run record

- Date: 2026-08-02; elapsed: 293.92 seconds (12:35:45Z–12:40:39Z).
- Commit at execution: `6cbbbed`.
- Workflow research id: `22fb8ef4-424f-4cfc-8a4b-bf65f6556ffe`.
- RAG ledger run id: `rag-e2e-845402c8-ad35-4783-afb8-a5ce26b2a013`.
- Configuration: Alibaba 2024 20-F topic; as-of `2026-07-01`; depth 1;
  `sec_companyfacts`; live LLM/search/RAG; database
  `data/runtime/047-assets.db`; index
  `finance_v1-43f11085-heading_page_first_1024_256`.

## Result

The preflight correctly rejected a missing paid confirmation and Qdrant reported
`exists`. The actual run invoked live search, SEC Company Facts, embeddings,
and reranking. One web fetch reached its independent timeout and degraded.
The bounded extractor then exhausted exactly three 60-second provider attempts
and raised `LLMRetryExhaustedError`. The workflow stopped without a fourth
attempt or a second paid run; no report was produced.

Recorded workflow LLM cost was CNY 0.00380948 and RAG-ledger cost was CNY
0.10917, totaling CNY 0.11297948, below the CNY 15 single-run and CNY 20 round
caps. The failed-run manifest records the requested index but is `mixed`, as
the extractor did not complete. The full offline gate passed: 739 tests, with
4 skipped.

## Decision

R072 is **INCOMPLETE** for every delivery-dependent T8 acceptance criterion:
there is no non-empty `report.md`, no completed `actual_realness=real`
manifest, and no audit citation closure in a report. The 48,000-character
bound did not make this provider/model complete extraction within 60 seconds.
Any design repair and subsequent paid experiment require a new preregistration
and a new user authorization.
