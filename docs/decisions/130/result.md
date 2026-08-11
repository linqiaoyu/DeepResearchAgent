# R130 — bounded Tool Calling Loop

## Verdict

PASS. H06 is complete and `tool_calling` is H2-ready. The Harness now exposes
explicit model intent, authorized call, and observation types plus a bounded
multi-round execution loop. Existing capability selection remains compatible.

## Control model

`ToolCallIntent` is only a suggestion. `ToolCallingLoop` resolves it against the
existing `CapabilityRegistry`, applies name allowlisting, paid-call and
side-effect authorization, then executes an `AuthorizedToolCall` through
`ReliableToolExecutor`. Every outcome becomes a typed `ToolObservation` and is
fed into the next proposal round.

The loop stops independently on maximum rounds, executed-call count, or
pre-call estimated CNY cost. Unknown, malformed, unallowlisted, paid, and
side-effecting intents can be rejected without resolving or invoking an
implementation. `LLMToolIntentProposer` adapts the existing `LLMClient`; the
recorded proposer provides offline exact replay.

## Falsification

The production paid-call authorization branch was temporarily removed. The
checker exited 1 and reported:

```text
unauthorized_tool_executions: expected 0, got 1
{"hard_limits_triggered": 3, "recorded_replay_match": 1.0, "sequential_tool_observations": 2, "unauthorized_tool_executions": 1, "unknown_tool_executions": 0}
```

The branch was restored. The self-test also rejects a single-step loop, unknown
execution, a missing hard limit, and replay drift.

The first real H2 promotion also exposed a checker defect: its
`h2_without_proof` mutation inherited an existing proof after promotion. The
self-test now deletes the proof field explicitly, so the negative case remains
falsifying before and after technologies graduate.

## Verification before complete gate

- Tool Calling checker: PASS, 6 cases.
- Unit suite: 4 tests pass.
- Measured: observations 2; unknown executions 0; unauthorized executions 0;
  limits 3/3; replay match 1.0.
- Ruff and scoped strict mypy pass.
- Paid/provider/network calls: none.

## Compatibility and boundary

The pre-existing `CapabilitySelection`, deterministic selector, and
`LLMCapabilitySelector` remain readable and unchanged. The new loop is default
inactive: no Settings default or finance product behavior changed.
