# 084 live-run preregistration

## Hypothesis and decision rule

On execution commit `bc966e0`, two real-provider runs will retain distinct SEC
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
