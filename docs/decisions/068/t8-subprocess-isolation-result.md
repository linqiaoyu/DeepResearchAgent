# T8 R068 result and production subprocess isolation

## R068 result

INCOMPLETE. The sole user-authorized attempt started with research ID
`4fe6bf0f-679c-487b-9f5e-5a50ea82c112`. It completed planner, real web search,
RAG setup, and SEC evidence (`www.sec.gov`), then reached extractor with 19
sources. Extractor remained in a provider SSL read without a completion or
failure event, so the owned process was terminated under the preregistered
stop rule. No report, final manifest, or citation closure was created. No
second live call was made.

## Repair

R068 demonstrates that a main-thread signal deadline alone is insufficient for
the production LiteLLM transport path. Production LiteLLM requests now run in
a spawned child process. The parent joins only for the configured deadline,
then terminates and reaps the child. This makes the SDK's own threads and
socket reads process-scoped and prevents them from keeping a workflow alive.
Injected test completions retain their existing in-process deadline paths.

The new offline guard starts a child that records its PID and blocks. It
asserts that timeout returns promptly and that `kill(pid, 0)` proves the child
was reaped. Mutating both termination branches makes the guard fail. The full
offline gate passed after the repair.

## Next action

No post-repair live validation occurred. A new user authorization and new
preregistration are mandatory before another real T8 experiment.
