# Service-level objectives

These are engineering objectives, not claims that a continuously operated production service exists. The public artifact is a static demo site; FastAPI and Streamlit are deployable local/demo paths.

| Signal | Objective | Current measured value | Status and source |
| --- | --- | --- | --- |
| End-to-end latency | P90 ≤ 300 s for a Golden question on the reference provider set | G3 saved generation states: P50 319.537 s; P90 463.268 s; maximum 736.605 s; n=30 | Measured generation latency; P90 target unmet. `_collab/008a_gold-v11/g3_*/Q*/state.json`, measured 2026-07-09T22:52Z through 2026-07-10T00:53Z |
| Run success | ≥ 99% requests complete without infrastructure error over a rolling 30 days | No rolling service telemetry; G3 saved judge set has 30 cases and 0 structured failures | Partial offline evidence only. `data/golden_set/v1/results/g3_judge_v11.json` |
| LLM cost | P90 ≤ ¥0.30 generation cost per Golden question | G3 saved generation states: P50 ¥0.173219; P90 ¥0.232623; n=30 | Measured token-price accounting; target met on this offline sample. The values are estimates, not provider invoices. Same saved states and `_collab/006f2_citation-repair-v2/gen3*ledger.jsonl` |
| Citation support | average ≥ 0.85 and no release regression beyond 0.01 | G3 v1.1 `avg_citation_support=0.8667`; citation support rate is 0.7640 | Measured offline. `data/golden_set/v1/results/g3_judge_v11.json` |

## Saved-generation latency breakdown

The end-to-end percentiles above were calculated with
`scripts/offline_metrics.py` after projecting each saved state's
`evaluation.latency_seconds` into one ledger row. Across all saved states,
that value agrees with `updated_at - started_at` to within 0.037 seconds.

The matching LLM ledgers support a narrower role-call breakdown:

| Recorded component | P50 call-time sum | P90 call-time sum | Maximum |
| --- | ---: | ---: | ---: |
| Planner | 12.085 s | 18.363 s | 23.263 s |
| Extractor | 250.235 s | 405.810 s | 627.167 s |
| Reporter | 42.280 s | 82.334 s | 88.687 s |
| All recorded LLM calls | 309.662 s | 451.392 s | 727.098 s |
| Non-LLM residual | 9.249 s | 10.296 s | 12.165 s |

These are sums of recorded call latencies, not independent wall-clock phase
traces. Extractor rows can include retry extraction. The saved artifacts do not
separately time retrieval, Critic and retry orchestration, or local evaluation;
those components remain combined in the non-LLM residual and must not be
reported as estimated phase measurements.

## Measurement rules

- Latency and cost comparisons require comparable run manifests: identical model strings, prompt hashes, as-of dates, flags, dependency versions, domain, and mode.
- P50/P90 must be computed from per-run observations. A mean derived from a saved aggregate is never relabeled as a percentile.
- Availability objectives start only after a long-running service and durable telemetry are commissioned. Until then, offline completion counts are not uptime.
- Default-off hardening features must be reported as dark and must not be counted as an active mitigation.

## Alert proposals

- Page on five consecutive infrastructure failures or an open supplier circuit lasting more than five minutes.
- Warn when daily LLM spend reaches 80% of the configured guard; stop paid demo runs at 100%.
- Block a release comparison when manifest comparability fails or prompt drift guard fails.
- Investigate citation support below 0.85 or a comparable-run regression greater than 0.01.

## Retrieval scaling triggers

The following are evaluation triggers, not evidence that a managed vector
service is currently required.  Assess a Qdrant tier upgrade only when at
least one condition holds: active chunks exceed 100,000; seven consecutive
days of the local fixture Stage-A retrieval measurement have p95 above 500 ms;
or seven consecutive days each ingest more than 10,000 chunks.  Do not add
sharding or Milvus before 1,000,000 active chunks.
