# T8 main-thread deadline live validation preregistration

Date: 2026-08-02

## Authorization and hypothesis

The user authorized exactly one new paid T8 attempt: CNY 15 per attempt and
CNY 20 for this round. This is a new experiment because R067 changed the
main-thread LLM deadline behavior after R066.

Hypothesis: one real Alibaba 2024 20-F run now completes delivery without the
extractor provider-worker shutdown failure, while using real LLM, web search,
RAG, and SEC Company Facts providers.

## Frozen configuration

- Code baseline: `f4e3c3f` plus this preregistration commit.
- Topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`.
- `as_of=2026-07-01`, depth 1.
- Structured provider: `sec_companyfacts`.
- RAG database: `data/runtime/047-assets.db`.
- RAG index: `finance_v1-43f11085-heading_page_first_1024_256`.
- Mode: `live --allow-paid-api`.
- LLM budget CNY 3; RAG budget CNY 12; total hard ceiling CNY 15.

## Acceptance and decision rule

The sole attempt must produce a non-empty `report.md`, final manifest, exact
retrieval index version, at least one RAG ledger row, manifest cost at most CNY
15, an audit citation-closure value in the report, and pass
`check_real_run_manifest.py --require-active-real`. Disclosure remains
optional; SEC structured data is expected for the Alibaba financial request.

Stop without retry if an active provider exhausts three retries, an attempt or
round breaker trips, or delivery fails. Preserve every result, including
absence of expected artifacts. Any later attempt requires new authorization
and preregistration.
