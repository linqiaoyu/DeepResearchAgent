# 087 final live-validation preregistration

Runnable source commit: `abe8dee339c3eef5c4b2dcff3fcd8e4c7d27cabc`.

The canonical gate passed on this source in
`_collab/087/evidence/gate_after_ab_promotions_retry.log`. The first attempt
is retained separately because the concurrent SQLite schema-race guard saw
`duplicate column name: published_at`; its immediate standalone reproduction
and the full retry passed without code changes.

Two primary, non-repeatable final runs are registered. Both use the same
source commit, depth 1, `--as-of 2026-07-01`, live mode, the read-only
`data/runtime/085-assets.db` corpus, index
`finance_v1-43f11085-heading_page_first_1024_256`, and an explicit
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts` export.

| Run | Topic | Output | Global allocation |
|---|---|---|---:|
| NIO | `蔚来 2024 年年报的营收与毛利情况` | `artifacts/087/live-nio-zh` | 24/45 |
| PDD | `PDD 2024 annual report revenue and gross margin` | `artifacts/087/live-pdd-en` | 25/45 |

Each run is capped by the existing CNY 15 per-run breaker. The round has
used 23 of 45 runs before this plan and reserves a single 26/45 contingency
only for an incomplete provider/package failure; it is not authorization to
rerun either completed topic for a better result. Stop all live work if the
CNY 30 round ceiling or a per-run breaker is reached. For each completed
package, record UTC time, commit, desensitized run id, configuration, result,
workflow cost, RAG cost, elapsed seconds, report-shape result, fidelity,
retrieval relevance, and structured-manifest validation.

The run is accepted only if its report shape passes; it has no internal
`typed coverage` or `Evidence 保真合同` wording; and the retained 086
fidelity conditions hold, including structured provider identity,
`audit_citation_closure=ok`, zero footnote and magnitude mismatches, and
NIO's two complete key findings. A failed acceptance check stops downstream
README/site claims for the affected package and is reported as incomplete; it
does not permit result-shopping.
