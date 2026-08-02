# T8 null-period live result

## Run record

- Date: 2026-08-02
- Commit at execution: `d249cdc`
- Research run id: `fd49e245-0a2a-4c44-8986-d08009f8aa1e`
- RAG ledger run id: `rag-e2e-b37a54c9-4ad6-4eb8-bc33-2e66bee12ba2`
- Configuration: Alibaba 2024 20-F topic; `as_of=2026-07-01`; depth 1;
  `sec_companyfacts`; live LLM/search/RAG; index
  `finance_v1-43f11085-heading_page_first_1024_256`.

## Result

The real planner, search, embedding, rerank, and extractor providers ran. The
extractor's first provider call timed out, its second call completed, and its
structured-output repair completed after two timeouts and a final successful
attempt. The workflow then failed before report delivery because a valid
nullable `NumericFields.period` reached the finance authoritative-backfill
deduplication helper, which called `.strip()` on `None`.

Recorded LLM cost was CNY 0.02881352 and recorded RAG cost was CNY 0.109221,
for CNY 0.13803452 total, under the CNY 15 cap. The output has no report; T8
acceptance is therefore not established. The real command was not retried.

## Repair and next experiment

`_period_year` now accepts `str | None` and returns no slot for an absent
period. The new test sends an LLM-derived claim with `period=None` through
authoritative backfill. Its mutation evidence removes the null normalization
and records the resulting failure. The full offline gate passed after repair.

Because this changed code after the paid run, any future live validation is a
new experiment and requires fresh authorization and preregistration.
