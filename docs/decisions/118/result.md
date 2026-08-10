# 118 result

R116 and R117 were validated by counterfactual: the shipped code called with the
30 saved R113 states' own inputs. That proves what the code does to those
states. AGENTS.md §7 is explicit that a run after a code change is a new
experiment, so this round ran one.

Preregistered before spending: four questions, deterministic measurements only,
CNY 8.00 round breaker, decision rule fixed in advance. Actual spend **CNY
1.18**.

## What the live run delivered

Real fidelity — LLM, search, structured data and judge all real.

| | R113 delivered | R118 live |
|---|---:|---:|
| Q30 report lines | 766 | **48** |
| Q30 reference lines | 736 | **8** |
| Q25 report lines | 148 | **44** |
| Q25 reference lines | 118 | **6** |
| Q16 reference lines | 33 | **7** |
| provider-series reference lines (4 questions) | 854 | **0** |
| orphaned sub-questions | — | **0 of 10** |

Q08 grew, 22 lines to 39: the evidence floor added the sub-question's own
evidence, which is what it exists to do.

These four questions were re-researched, so retrieval and sampling differ from
R113 as well as the code. A 736-to-8 reference count is not attributable to that
variation; the per-question judge scores are not quoted here for the same
reason, and this is a four-question subset that may not be compared to any
30-question round.

## The regression this run caught

Q08's first live report cited `[^1]` and `[^4]` from 指标覆盖状态 with neither
defined. R117 filtered the reference list inside the two renderers, and
`_append_metric_coverage` adds its section *after* the reference list is
written, so those citations did not exist when the filter ran.

The gate had not caught it, and the reason is worth recording: the guard was
pointed at the demo report, and the demo topic requests no metrics, so the only
artifact under assertion could not exhibit the defect. A guard is bounded by the
artifact it is aimed at.

The first attempt at the fix reproduced the bug. Pruning after assembly still
split the page at the reference heading and counted citations only above it,
which drops exactly the references cited below it. Both the pruner and the guard
now identify definitions by their shape and count citations from every other
line, which does not depend on where anything sits.

Re-run live after the fix: `references=5 never_cited=0 unresolved=0`.

## A negative result worth more than the positive ones

Q08 ran live twice, on code differing only by the pruning pass, and returned
`false_premise_failed=False` the first time and `True` the second. The second
report states 1741.44亿元 and 「确认2024年增长趋势」 but not the 15.66%
year-on-year the frozen gold requires, so the criterion fails, correctly.

**`false_premise_failed` varies run to run at n=1.** The counterfactual showed
it flipping on fixed inputs; live, with retrieval and sampling free to move, one
sample cannot establish it. Nothing in this round claims that criterion moved in
production, and §7 forbids re-running until it does.

The structural metrics held in both runs, which is why they were the
preregistered ones: 0 orphaned sub-questions, 0 never-cited references, 0
unresolved markers, 0 provider-series reference lines.

## Verdict against the preregistration

| prediction | result |
|---|---|
| orphaned sub-questions → 0 | **held** (0 of 10) |
| never-cited references → 0 | **held after the fix**; the first run exposed a regression |
| provider-series references order-of-magnitude fewer | **held** (854 → 0) |
| `false_premise_failed` ≤ 1/2 | **not established**; the metric is not stable at n=1 |

## Gate

```
Ran 1132 tests in 60.036s
OK (skipped=7)
reference_list_self_test=PASS cases=6
reference_list=PASS references=3 body_lines=15 never_cited=0 unresolved=0
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

## Not established

- **The research loop is still off.** The 12 gold facts never retrieved in R113
  are still not retrieved, and the sufficiency gaps the loop would iterate on
  still name `counterargument` and `freshness` rather than the question's own
  target.
- **Nothing here is a quality score.** Four questions, one judge sample, and a
  subset chosen for what it predicted.
