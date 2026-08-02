# T8 SEC Company Facts retry result

## Result

INCOMPLETE. The one authorized live attempt did not create a report or a final
manifest, so none of the delivered-report acceptance assertions can be
claimed. No second live call was made.

## Recorded attempt

- Started: 2026-08-02T11:33:07Z.
- Research ID: `23b9dbd3-649e-4314-987d-fb02216e9d69`.
- Baseline: `4b83551` (which includes the LLM hard-timeout repair).
- Frozen mode and inputs: live LLM/Tavily/SEC Company Facts/RAG, Alibaba 2024
  20-F question, depth 1, `as_of=2026-07-01`, and the preregistered RAG index.
- Completed before failure: real planner and web searches; package-local RAG
  ledger was created. The process reached extractor with 28 sources.
- Failure: extractor did not produce a completed node event or delivery files.
  Process samples show SSL reads in provider workers. After the three
  configured 60-second windows and retry backoff had elapsed, the owned process
  was terminated at 2026-08-02T11:37:00Z under the preregistered stop rule.

The LLM hard-timeout wrapper prevented silently waiting in the workflow call,
but this run still retained provider-side worker threads past the bounded
attempt windows. That is a new repair candidate; it is not validated or
presented as fixed here because any code change would require another newly
authorized live experiment.

## Evidence and next action

Raw preflight, live log, and two samples are retained in the ignored R066
evidence directory. No report, final manifest, or audit citation closure
exists. A future attempt needs new authorization and preregistration after an
offline repair and full-gate verification of provider-worker shutdown.
