# 119 result

R118 closed by naming the research loop as the remaining gap. Measuring the gap
first moved the round somewhere else.

## Where the twelve missing facts actually were

Of the golden set's 50 numeric facts, R113 never retrieved 12. They are not
spread across the set:

| question | missing facts | evidence collected | sources |
|---|---:|---:|---:|
| Q03 | 4 | 0 | 0 |
| Q05 | 5 | 0 | 0 |
| Q13 | 1 | 142 | 22 |
| Q16 (partial) | 2 | 155 | 33 |

Ten of the twelve belong to two questions that retrieved **nothing at all**:

```
Q03  status=budget_exceeded  sources=0  evidence=0  search_records=0
Q05  status=budget_exceeded  sources=0  evidence=0  search_records=0
terminal_failure = "run-wide web fetch request budget exhausted
                    for tavily_search: 20/20"
```

Their own budget snapshots record six searches and twenty fetches already
accepted. The work had been done; the twenty-first fetch was refused, the
`ToolExecutionError` unwound the graph, and nothing reached `research_join`.

So the largest remaining retrieval gap was never a research strategy, and
opening the loop would not have touched it.

## The gate that was wrong

```python
except ToolExecutionError as exc:
    if exc.kind != ToolErrorKind.BUDGET_EXCEEDED:
        raise
    if not authority_returned:      # <-- here
        raise
```

Degradation was conditional on a first-party disclosure having come back.
Q03 and Q05 were web-only branches, so `authority_returned` was False and both
re-raised. AGENTS.md §6 requires every external tool to have
「有界 timeout、retry、请求预算和显式降级」; the budget existed and the
degradation did not.

The condition is now whether anything was obtained at all. That keeps the one
case where terminating is accurate -- a budget that refuses the *first* request
means the run could not begin -- so the existing budget-zero contract, and the
test asserting it, are unchanged.

## Live validation

Preregistered, authorised, CNY **0.31** against a 5.00 breaker.

| | R113 | R119 live |
|---|---|---|
| Q03 | `budget_exceeded`, 0 sources, 0 evidence | **`done`, 22 sources, 85 evidence** |
| Q05 | `budget_exceeded`, 0 sources, 0 evidence | **`done`, 18 sources, 49 evidence** |
| Q03 gold facts retrieved | 0/4 | **4/4** |
| Q05 gold facts retrieved | 0/5 | **4/5** |
| orphaned sub-questions | — | 0/3 and 0/3 |
| reference hygiene | — | PASS both, `never_cited=0 unresolved=0` |

Eight of the ten facts these questions had never seen are now in evidence. The
ninth and tenth are Q05's four quarterly figures, of which one is still absent.

## The class, and the fifth budget

The instance was one branch of one method. The class is every run-wide external
request budget, so `scripts/check_budget_degradation.py` enumerates them from
`Settings` and fails closed on any that is not registered.

It immediately found one this change had not considered: `max_searches_per_run`,
the run quota. It already degrades -- `SearchQuota.consume` returns False rather
than raising -- but nothing said so, and nothing would have failed if that
changed. It is registered with its own test.

A budget registered as `degrade` must name a test proving an exhausted budget
keeps the work already done, and the guard **runs that test**, so a registration
cannot outlive the behaviour it claims. The number allowed to terminate is a
ratchet at 0.

The four self-test cases include restoring the pre-R119 disposition, which the
guard rejects.

## A second, smaller defect

`_mechanical_metrics` returned `{}` whenever `state.evaluation` was missing, and
took the reader metrics with it -- which is why the Q03 validation reported
`orphaned=None` while Q05 reported a number. Those metrics read the report and
the footnote map, not the evaluation, and a run that finished without an
evaluation is exactly the one whose delivered page is worth measuring.

Measured offline from the saved states: Q03 `orphaned=0/3, reachable 65/85
(76%)`, Q05 `orphaned=0/3, reachable 44/49 (90%)`.

## Gate

```
budget_degradation_self_test=PASS cases=4
budget_degradation=PASS declared=5 degrade=5 terminate=0 ratchet=0
Ran 1137 tests in 58.695s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

The five new tests were run against the pre-R119 implementation and two of them
error, which is the counterexample AGENTS.md §2 requires.

## Not established

- **The research loop is still off.** This round removed the reason the loop
  looked necessary for Q03/Q05; it did not open it. The remaining retrieval
  gaps are Q13's one fact and Q05's fourth quarter.
- **Two questions is not the golden set.** No score is quoted from this run.
