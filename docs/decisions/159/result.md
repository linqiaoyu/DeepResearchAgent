# R159 — F12 budget-aware retry and terminal integrity

## Decision

PASS. The single reliability class exposed by the R158 canary is closed with
two fail-closed controls. Critic retry preparation now receives the run scope,
reads the shared external-search ledger, and schedules no more retry tasks than
the remaining allowance can cover under the existing two-search upper bound of
`ResearcherAgent.retry`. Tasks outside that capacity are not launched: they
remain in the retry queue as explicitly completed degradations, receive an
`[external_search_budget_deferred]` search record, and are listed in a
`retry_budget_scheduling_events` manifest locator with the budget snapshot and
scheduled/deferred task IDs.

The golden runner now dispatches scoring only for workflow `status=done`.
`budget_exceeded`, `failed`, `paused`, or `running` state is persisted as an
outer `status=error` with the original `workflow_status`, terminal reason,
research ID and evidence funnel. No judge or citation-support request is made
for such partial output. `_score_case` independently rejects non-done state so
future callers cannot bypass the dispatcher.

## Scope and evidence

- The completed retry path remains covered by the existing three integration
  cases; all completed tasks retain their original sub-question attribution.
- A two-request remainder with three official-source retry tasks schedules one
  and explicitly defers two. A zero remainder launches none and routes directly
  to the join node.
- The runner probe uses the real R158 terminal shape (`budget_exceeded` plus a
  partial state) and proves no judge method is reached.
- `mutation-retry-overfanout.txt` records the failure when all pending tasks are
  launched despite only one task's upper-bound capacity.
- `mutation-score-terminal-state.txt` records the failure when both terminal
  checks are removed and the runner attempts to call the judge.
- Paid calls, canary reruns, full-cohort runs, golden changes, threshold changes,
  and remote writes: 0.

This repair is a targeted Harness reliability proof, not financial product
quality evidence. R158 remains historically failed; no result was rewritten or
spliced. The next planned full live product run is F14/R160.

The complete local gate passed with 1,225 tests, 7 registered skips, 61/61
guards wired, and tracked files unchanged.
