# T8 latency-budget live validation preregistration

Date: 2026-08-02

The user authorized one paid T8 attempt up to CNY 15 and a CNY 20 round cap.
Commit `d9f98e5` reduces the extractor provider payload to 12,000 characters,
4,000 per source, and 1,024 completion tokens after R072's three 60-second
timeouts. This is a new experiment.

Hypothesis: one bounded real run produces a non-empty report and a complete
manifest with real LLM, search, structured-data, and RAG layers. Frozen
configuration: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`; as-of
`2026-07-01`; depth 1; structured provider `sec_companyfacts`; database
`data/runtime/047-assets.db`; index
`finance_v1-43f11085-heading_page_first_1024_256`.

The LLM/RAG/total caps are CNY 3/CNY 12/CNY 15, within the CNY 20 round cap.
Stop with no rerun on provider retry exhaustion, cost breaker, provider failure,
or delivery failure. Preserve raw evidence. A subsequent paid command requires
new authorization and preregistration.
