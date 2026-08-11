# R129 — Tool lifecycle and fault isolation

## Verdict

PASS. H05 is complete and `tool_use` is the first technology promoted from
`wired` to `h2_ready`. Its proof combines H04's 100% external-call control
coverage with this round's seven error-kind lifecycle probe.

## Measured lifecycle

- All seven `ToolErrorKind` values execute through the production
  `ReliableToolExecutor` and retain their typed outcome.
- A blocked synchronous provider crosses its attempt deadline once, returns a
  detached-timeout result, and is not retried concurrently: operation calls 1,
  attempts 1.
- Six initialize/list/close MCP subprocess cycles per probe emit zero
  subprocess or file-handle `ResourceWarning`; three consecutive complete
  probes produced the same zero count.
- A real workflow with zero search-request budget finishes as
  `budget_exceeded` while preserving the completed plan, todo list, topic,
  final report, and gated decision.

## Falsification

The production fail-fast branch for `DetachedToolOperationError` was removed
temporarily. The local lifecycle checker exited 1 with:

```text
timeout_attempts: expected 1, got 3
{"budget_state_preserved": true, "resource_warnings": 0, "timeout_attempts": 3, "timeout_operation_calls": 1, "tool_error_kinds_exercised": 7}
```

The mutation was restored before verification. Four in-memory negative cases
also reject a missing error kind, overlap, resource leak, and lost state.

## Verification before complete gate

- Tool lifecycle self-test: PASS, 5 cases, repeated 3/3.
- External-call closure remains 9/9 and 1.0.
- Ruff and scoped strict mypy pass.
- Paid/provider/network calls: none.

## Boundary

Successful Tool results and business semantics are unchanged. The probe uses
only local deterministic execution and local stdio subprocesses.
