# T8 SEC Company Facts retry preregistration

Date: 2026-08-02

## Authorization and hypothesis

The user authorized one new T8 paid live attempt, capped at CNY 15 per attempt
and CNY 20 for this round. The previous attempt is not reused: its code
baseline changed to enforce a harness-level LLM deadline.

Hypothesis: one bounded real run now completes the delivered report and active
provider manifest while using real LLM, search, RAG, and SEC Company Facts
providers for Alibaba's 2024 20-F question.

## Frozen configuration

- Code baseline: `15592f4` plus this preregistration commit.
- Topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`.
- `as_of`: `2026-07-01`; depth: `1`.
- Structured provider: `sec_companyfacts`.
- RAG database: `data/runtime/047-assets.db`.
- RAG index: `finance_v1-43f11085-heading_page_first_1024_256`.
- Mode: `live --allow-paid-api`.
- Workflow LLM hard budget: CNY 3; RAG hard budget: CNY 12; registered
  per-attempt total: CNY 15.

## Measurements and decision rule

The one run must write a non-empty `report.md`, retain the requested retrieval
index version, record at least one RAG embedding or rerank row, have manifest
cost at most CNY 15, and pass:

```
PYTHONPATH=src .venv/bin/python scripts/check_real_run_manifest.py \
  <manifest> --require-active-real
```

The report must contain the audit citation-closure value. Disclosure is
optional under active-provider acceptance. SEC structured data is expected to
be used; if the planner legitimately makes no structured request, it must be
explicitly unused without a structured-provider degradation event.

## Stop and rollback

No tuning and no second live call. Stop immediately if an active provider
exhausts three retries, any cost breaker is reached, or delivery fails. Preserve
the raw log, run IDs, ledger rows, manifest or absence thereof, elapsed time,
cost, and negative outcome. Any further retry requires new user authorization
and a new preregistration.
