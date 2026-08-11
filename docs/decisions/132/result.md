# R132 — bounded replanning and Research Loop H2

## Verdict

PASS. H08 is complete and `planning_replanning` is H2-ready. The existing
`BoundedLoop` independently stops on maximum iterations, call budget, and a
consecutive no-progress window. A sufficiency result containing only
non-researchable gaps stops before refinement, so it schedules zero new
searches. Replaying the same recorded tracker inputs produces the same route.

## Lifecycle closure

R131 exposed a follow-on issue in the loop path: the execution-plan step became
`succeeded` after the first research join, so later refinement rounds remained
mapped but their usage was not accumulated. `PlanLifecycle.restart` now opens a
new bounded attempt while preserving cumulative usage. Research preparation
starts or restarts every mapped branch before LangGraph fan-out; research join
may consume and complete only a `running` step. Loop-enabled plan budgets cover
the configured maximum attempts, while the stricter shared `BranchBudget`
continues to cap actual run calls.

## Boundary

The capability remains default-off and no financial-quality benefit is claimed.
Finance still owns query-refinement policy through the injected DomainPack;
the Harness owns lifecycle, routes, and hard bounds.

## Verification before complete gate

- Replanning checker: iteration/budget/no-progress 3/3; no-actionable-gap new
  searches 0; recorded route match 1.0.
- Planning execution mapping remains 1.0.
- Paid/provider/network calls: none.

## Falsification

The production `BoundedLoop` no-progress boundary was temporarily replaced by
a no-op. The real checker exited 1 with
`replanning_loop_self_test=FAIL production probe is dirty`. Restoring the
boundary returned all four metrics to their contracted values. Checker
self-tests separately reject each missing bound aggregate, useless new search,
unmapped task, and replay route drift.
