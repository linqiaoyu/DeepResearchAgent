# T8 real E2E post-environment-repair preregistration

Date: 2026-08-02
Commit: recorded by the commit that introduces this file.

## Authorization and prior attempts

The user explicitly authorized T8 at CNY 15 and subsequently supplied fresh
authorization after the earlier zero-cost attempts stopped before provider
construction.  Round 058 rebuilt the local virtual environment from the
project's pinned dependency declarations and then verified `pandas` and
`akshare` imports.  This preregistration governs one new live attempt only.

## Hypothesis and configuration

One bounded live research package will produce a non-empty cited report and a
complete manifest proving all three layers are real: workflow LLM, external
search/structured-data, and RAG retrieval.

- Topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`
- `as_of`: `2026-07-01` (after the corpus document publication dates)
- Depth: 1
- RAG store: `data/runtime/047-assets.db`
- Frozen index version: `finance_v1-43f11085-heading_page_first_1024_256`
- Mode: `live` with explicit `--allow-paid-api`

## Measurement and decision rule

The attempt passes only if the output report is non-empty; its manifest has
`actual_realness == "real"` and the stated retrieval index version; the RAG
ledger includes at least one embedding or rerank call; total reconciled cost is
at most CNY 15; and the report preserves `audit_citation_closure` exactly as
printed by the package command.  Record all outcome values, including a
failure, without rerunning or tuning.

## Cost and rollback

- Per-attempt circuit breaker: CNY 15, split as workflow LLM CNY 3 and RAG CNY
  12.
- Whole-round circuit breaker: CNY 20.
- If any provider layer exhausts three retries, or either circuit breaker is
  reached, stop the attempt and preserve the evidence.  No follow-up paid run
  is permitted under this preregistration.

## H7 ledger reconciliation

The package output will name the workflow `research_id` and the distinct RAG
ledger `run_id`, then report the RAG cost summary alongside the workflow
result.  This preserves the existing ledger schema while making the two run
identifiers and their cost attribution explicit.
