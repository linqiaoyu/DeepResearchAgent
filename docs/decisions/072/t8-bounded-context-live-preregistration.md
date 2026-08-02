# T8 bounded-context live validation preregistration

Date: 2026-08-02

The user authorized one paid T8 attempt up to CNY 15 and a CNY 20 round cap.
Commit `0db7428` bounds the extractor LLM source context to 48,000 characters
after R071 exhausted all three provider attempts on an unbounded 28-source
payload. This is a new code version and therefore a new experiment.

Hypothesis: one bounded real run produces a non-empty report and a complete
manifest, with real LLM, search, structured-data, and RAG layers. Frozen run:
`阿里巴巴 2024 年 20-F 财务表现与风险因素研究`; as-of `2026-07-01`;
depth 1; structured provider `sec_companyfacts`; database
`data/runtime/047-assets.db`; index
`finance_v1-43f11085-heading_page_first_1024_256`.

The LLM/RAG/total caps are CNY 3/CNY 12/CNY 15, within the CNY 20 round cap.
Stop with no retry on any provider retry exhaustion, cost breaker, provider
failure, delivery failure, or total-cost breach. The script already uses
`engine.close()` and reports the workflow research id alongside the distinct
RAG-ledger run id for cost reconciliation. Preserve all raw evidence. Any
later paid command requires a new authorization and preregistration.
