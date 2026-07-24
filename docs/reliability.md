# Reliability and offline failure drills

The default deterministic path enables the typed search contract, bounded
retry budget, exponential backoff with jitter, and a three-state circuit
breaker. The drills use only fixture providers and injected exceptions. They
make degradation visible in `ResearchState.metadata`, run manifests, and the
final report's `数据获取降级` section.

| Scenario | Expected behavior | Measured behavior |
| --- | --- | --- |
| One transient failure | Retry once, recover, record the recovered degradation | Passed; two attempts, deterministic backoff, report and manifest visibility |
| Continuous failure | Stop when the run retry budget is exhausted | Passed; `budget_exceeded` recorded, no unbounded retry |
| Timeout | Apply the timeout retry policy and end in an explicit degradation | Passed; bounded attempts and timeout event |
| Rate limit | Apply the rate-limit-specific backoff | Passed; rate-limit reason, two attempts, expected longer backoff |
| Authentication failure | Do not retry the failed tool call | Passed; one attempt, no backoff, explicit auth degradation |
| Circuit breaker | Fast-fail while open; allow a half-open probe after cooldown | Passed; zero-attempt fast failure, then half-open probe and close on success |
| Partial subquestion failure | Continue successful subquestions and mark coverage loss | Passed; report produced with evidence and an explicit coverage warning |
| Total retrieval failure | Never emit an unqualified evidence-free report | Passed; task success is zero, the summary says evidence is insufficient, and provider degradation is listed |

The total-failure path previously included a generic “insufficient evidence”
summary but omitted the provider reason, attempts, retry-budget state, and
circuit impact. The drill added explicit degradation propagation and
reader-visible reporting; it did not invent fallback evidence.

## What this project does not handle

- No automatic cross-provider failover.
- No infinite retries and no retry-budget reset inside a run.
- No claim that fixture exception injection validates Tavily or another real
  provider's error payloads; that boundary remains for provider integration.
- No distributed circuit-breaker state across processes.
- No durable telemetry sink, paging policy, or rolling production error-rate
  baseline.
- No automatic suppression of a report solely because one subquestion failed;
  the failure is surfaced and successful evidence remains available.
