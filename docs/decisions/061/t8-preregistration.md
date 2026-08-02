# T8 real three-layer E2E retry preregistration

Date: 2026-08-02
Commit: recorded by the commit that introduces this file.

## Authorization and scope

The user explicitly authorized one new T8 attempt with a CNY 15 per-attempt
circuit breaker and a CNY 20 whole-round circuit breaker. This preregistration
governs exactly one live provider invocation on the current code revision,
after zero-cost configuration and index preflight succeeds.

Round 059 completed a live workflow but produced `actual_realness=mixed` and
then failed report finalization with `KeyError: 'cost_cny_total'`. Round 060
repaired that aggregation-key contract and passed the full local gate. This is
a new experiment, not a rerun to select a better result.

## Hypothesis and frozen configuration

One bounded live research package will write a non-empty cited report and a
complete manifest proving the workflow LLM, external search/structured-data,
and RAG retrieval are all real.

- Topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`
- `as_of`: `2026-07-01`
- Depth: 1
- RAG store: `data/runtime/047-assets.db`
- Frozen index version: `finance_v1-43f11085-heading_page_first_1024_256`
- Mode: `live` with explicit `--allow-paid-api`
- Workflow budget: CNY 3
- RAG budget: CNY 12

## Measurements and decision rule

The attempt passes only when all of the following are true:

1. `report.md` is non-empty.
2. Manifest `actual_realness` is exactly `real`.
3. Manifest `retrieval_index_version` equals the frozen index version.
4. The RAG ledger contains at least one embedding or rerank call and the
   reconciled RAG cost is at most CNY 15.
5. `audit_citation_closure` is copied into the report without alteration.

Any failed condition is an INCOMPLETE result. The result will be recorded as
observed and no configuration tuning or second paid run is permitted under this
authorization.

## Rollback and audit handling

Stop the attempt if any provider layer exhausts three retries, the CNY 15
per-attempt circuit breaker trips, or the CNY 20 whole-round circuit breaker
trips. Preserve raw output, run identifiers, configuration, elapsed time, and
both workflow and RAG ledger totals. The output will explicitly name the
workflow `research_id` and distinct RAG ledger `run_id`; this is the permitted
H7 reconciliation approach.
