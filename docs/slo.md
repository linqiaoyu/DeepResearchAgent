# Service-level objectives

These are engineering objectives, not claims that a continuously operated production service exists. The public artifact is a static demo site; FastAPI and Streamlit are deployable local/demo paths.

| Signal | Objective | Current measured value | Status and source |
| --- | --- | --- | --- |
| End-to-end latency | P90 ≤ 300 s for a Golden question on the reference provider set | G3 saved round total 13,574.390 s / 30 cases = 452.480 s mean per case; P90 was not recorded | Measured mean only; target unmet/unknown P90. `data/golden_set/v1/results/g3_judge_v11.json` |
| Run success | ≥ 99% requests complete without infrastructure error over a rolling 30 days | No rolling service telemetry; G3 saved judge set has 30 cases and 0 structured failures | Partial offline evidence only. `data/golden_set/v1/results/g3_judge_v11.json` |
| LLM cost | P90 ≤ ¥0.30 generation cost per Golden question | G3 saved total generation cost ¥5.188703 / 30 = ¥0.172957 mean per case; P90 was not recorded | Measured mean only. `data/golden_set/v1/results/g3_judge_v11.json` |
| Citation support | average ≥ 0.85 and no release regression beyond 0.01 | G3 v1.1 `avg_citation_support=0.8667`; citation support rate is 0.7640 | Measured offline. `data/golden_set/v1/results/g3_judge_v11.json` |

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
