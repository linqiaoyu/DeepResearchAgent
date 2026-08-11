# R131 — executable Planning contract

## Verdict

PASS. H07 is complete. Planning remains `wired`, not H2-ready, until H08 proves
the three replanning/research-loop bounds and deterministic routing required by
the frozen H2 registry.

## Contract

The Harness now owns a domain-neutral `ExecutionPlan` with typed `PlanStep`,
`PlanBudget`, and `PlanUsage` records. Every step carries its objective, status,
budget, success condition, dependencies, measured usage, and completion
evidence. `PlanLifecycle` is the only supported mutator: it rejects unknown
executions, unmet dependencies, per-step or aggregate overruns, and success
without evidence.

The existing finance-owned `ResearchPlan` remains the strategy source. The
planner node adapts its sub-questions into the generic execution contract, the
research preparation node refuses an unplanned branch, and research join marks
the mapped step complete with observed call usage. No second domain or graph
runtime was added.

## Falsification

The production validation that rejects the sum of step budgets exceeding the
plan budget was temporarily replaced with a no-op. The real checker exited 1:

```text
planning_contract_self_test=FAIL production probe is dirty
```

The validation was restored. Checker negative cases also reject a missing
required field, unmapped execution, unused field, invalid dependency,
over-budget declaration, and unknown executed task.

## Verification before complete gate

- Planning checker: PASS, 7 cases.
- Planning unit suite: 4 tests pass.
- Workflow/trajectory/research-loop/branch-budget regression: 40 tests pass.
- Ruff and strict mypy for new contract/checker/tests pass.
- First checker invocation omitted `PYTHONPATH=src` and failed import; the
  command was corrected and rerun as required by repository guidance.
- Paid/provider/network calls: none.

## Compatibility

No fields were added to the recorded `ResearchPlan` schema, so existing
completed trajectory parsing semantics remain intact. Execution lifecycle data
is additive run metadata. Persisted pre-R131 states and direct node callers are
adapted explicitly and tagged `execution_plan_origin=legacy_state_adapter`
before any branch can execute. Replanning behavior and default flags are
unchanged; H08 will extend this lifecycle across controlled refinements.
