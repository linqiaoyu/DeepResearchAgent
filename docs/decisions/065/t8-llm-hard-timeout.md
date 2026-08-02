# T8 live attempt: LLM hard-timeout repair

## Observed result

The one authorized live attempt started on 2026-08-02 and used the real LLM,
web, RAG, and SEC Company Facts providers.  It produced a successful planner
call, real SEC evidence, real embedding/rerank ledger rows, and one extractor
response.  The extractor then began a subsequent provider read that remained
blocked beyond the configured 60-second transport timeout.  The process was
stopped to enforce the registered no-retry rule; it did not produce a report
or a complete manifest, so T8 acceptance remains incomplete.

The raw process sample shows the main thread blocked in an SSL socket read.
The existing `timeout` argument supplied to LiteLLM did not constitute a
harness-level deadline: the recorded extractor response already took 64.753
seconds despite its 60-second configured timeout.

## Decision

`LLMClient` now runs each synchronous SDK call in a daemon worker and waits no
longer than the configured role timeout.  Overdue calls are quarantined, and a
process-wide bounded semaphore caps the number of detached workers at 16.  The
existing transport `timeout` remains in the provider request for normal I/O
cancellation.  This preserves the LLM ledger/budget path and turns a stuck
call into the existing retryable `LLMClientError` path.

The unit guard blocks its fake provider, verifies prompt return, reservation
release, and the quarantine error.  Removing the hard-timeout wrapper makes
that guard fail.  The full offline gate passed after the repair.

## Next action

No additional live call was made.  A fresh paid authorization and a new
preregistration are required before a new T8 attempt, because this attempt is
already consumed and code changed after it.
