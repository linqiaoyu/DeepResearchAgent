# T8 retry-exhaustion stop decision

## Context

The R069 paid T8 run used real LLM, search, and SEC Company Facts providers.
The planner completed, but the extractor's provider call timed out three times.
The subprocess timeout boundary reaped each timed-out child; the surrounding
agent then selected its deterministic fallback and the workflow initiated a
fourth LLM provider call. That violated the preregistered condition to stop
the experiment when a provider exhausts its retry budget.

## Decision

`LLMClient` now raises `LLMRetryExhaustedError` after all configured attempts
fail. Engines in `llm` mode set `fail_on_retry_exhaustion=True`, and the
planner, extractor, and reporter re-raise this sentinel rather than choosing a
deterministic fallback. Non-live callers retain their existing fallback
behavior unless they explicitly enable the flag.

## Evidence and consequence

The guard's mutation evidence is recorded in the R069 collaboration evidence:
removing the extractor re-raise makes
`test_strict_retry_exhaustion_stops_extractor_without_fallback` fail. The full
offline gate passed after restoration. No paid rerun was made after this code
change; a future real run is a new experiment and needs fresh authorization.
