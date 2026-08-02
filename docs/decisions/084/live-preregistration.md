# 084 live-run preregistration

## Hypothesis and decision rule

The initial NIO run on `14acc82` completed workflow execution but failed while
exporting the audit bundle because serialised JSON was redacted as raw text.
Commit `a6f24b0` redacts JSON leaves instead; this is a bounded export repair,
not a change to providers, topics, model, retrieval, or evidence semantics.
The allowed single retry for NIO and the fixed PDD run therefore execute on
`a6f24b0` plus this preregistration amendment. Two real-provider runs will retain distinct SEC
revenue and gross-profit facts from a shared filing, will export RAG reporting
period ends without inventing publication dates, and will not emit relative web
URLs. The NIO report must cite both structured facts and the package probes must
report `rag_pub_date_fabricated=0` and `relative_urls_in_evidence=0`.

## Fixed runs

1. Chinese: `蔚来 2024 年年报的营收与毛利情况`
2. English: `PDD 2024 annual report revenue and gross margin`

Both use `--as-of 2026-07-01 --depth 1 --mode live --allow-paid-api`, the
existing `data/runtime/047-assets.db` and
`finance_v1-43f11085-heading_page_first_1024_256` index, and explicitly set
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts`.

## Cost controls and rollback

The approved ceiling is CNY 15 per run and CNY 20 total. Stop immediately if a
single run exceeds its ceiling or the aggregate reaches CNY 20. A failed run may
be retried once, with at most three attempts total. Any provider layer that
falls back to fixtures is labelled mixed. No model, retrieval, topic, or
reranking settings will change between runs; a failed acceptance criterion is
recorded rather than optimized by repeated runs. If an acceptance regression is
observed, retain the packages and revert the responsible code after diagnosis.
