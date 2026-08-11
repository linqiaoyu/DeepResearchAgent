# 120 result

The round was "open the research loop and prove it changes behaviour". The
preregistered experiment says: **do not open it**, and explains why in three
constants.

## What the loop iterates on

Across the 30 R113 states, gap frequency over all sub-questions:

| gap | count |
|---|---:|
| `counterargument` | 63 |
| `unresolved_critic_issues` | 41 |
| `freshness` | 28 |
| `independent_source_domains` | 11 |
| `requested_metric_coverage` | 8 |
| `evidence_count` | 6 |
| `average_confidence` | 6 |

`stop_requested` was `sufficiency.sufficient`, so any of these kept the loop
running -- including `freshness`, which no iteration can close. The golden set is
evaluated at 2026-07-09 and asks about FY2024, whose filings were published in
early 2025, so on the 28 sub-questions carrying that gap the **freshest evidence
already held** is a median of **471 days** old (min 433). Source age is a
property of the question's time anchor, not of research effort.

The loop now asks `sufficiency.answered` -- whether any gap remains that another
iteration could close. Questions it would iterate on: **28/30 → 25/30**; three
were driven by `freshness` alone. `ResearchSufficiency.sufficient` is unchanged
and still reports every gap.

A test asserts that every gap kind `evaluate_research_sufficiency` can emit is
classified, so a new one cannot be silently ignored by the loop.

## The experiment

Preregistered before spending, with the decision rule and the noise floor fixed
in advance. Two arms, same questions, same code, one setting.

| arm | Q | evidence | gold in evidence | gold in report | loop iterations | cost |
|---|---|---:|---:|---:|---:|---:|
| A control | Q13 | 61 | 1/2 | 1/2 | – | – |
| A control | Q16 | 152 | 4/4 | 1/4 | – | 0.49 |
| B loop on | Q13 | 156 | 1/2 | 1/2 | 1 | 0.59 |
| B loop on | Q16 | 161 | 4/4 | 3/4 | 1 | 0.52 |

Arm B cost CNY 1.10 against arm A's 0.49 -- **2.2x** -- and retrieved **no
additional gold fact** on either question. The preregistered rule required
strictly more gold tokens on both questions *and* iterations that actually ran.
Neither held. **The default stays closed.**

The Q16 report difference (1/4 → 3/4) is not attributable to the loop, because
the loop never refined. It is run-to-run variation of the kind R118 recorded.

## Why no iteration ran

`research_process` shows one iteration per question and `research_refine` never
appears. The recorded decisions give the mechanism exactly:

```
Q13  budget_used=20  budget_ceiling=20  boundaries_triggered=['budget_ceiling']
Q16  budget_used=17  budget_ceiling=20  boundaries_triggered=[]
     outcome = stop_budget_constrained:因预算约束提前收敛
```

Three constants:

| setting | value |
|---|---:|
| `max_searches_per_run` (the branch pool) | 20 |
| `research_loop_budget_ceiling` | 20 |
| `decision_weaving_budget_remaining_ratio` | 0.2 |

The loop's ceiling is the same number as the pool the first pass is sized to
spend. So the first pass ends either at the ceiling (Q13, 20/20) or with ≤20%
remaining (Q16, 17/20 → 0.15), and both stop the loop. **A second iteration is
reachable only if the first pass uses 15 or fewer of its 20 calls.**

This is the third time a capability has been "enabled" and inert: R109's
`RESEARCH_LOOP_ENABLED` with `max_iterations` defaulting to 1, R111's
`RAG_ENABLED` with no retrieval service behind it, and now a loop whose budget
is spent before it can turn. The first of those is fixed -- the run refused
`RESEARCH_LOOP_ENABLED=true` with `max_iterations=1` and said so, which is how
this experiment's first launch failed. The budget sizing is not.

## Not established

- **Whether iterating helps.** The experiment could not answer it, because no
  iteration ran. Sizing the loop's budget above one pass is the prerequisite,
  and it is a separate change with its own experiment.
- **n is 2 questions per arm.** Even had the loop run, R118's finding stands:
  one live sample cannot separate a code effect from run-to-run variation.

## Gate

Two runs. The first was red:

```
FAIL: test_independent_request_engines_share_wal_checkpoint_safely
AssertionError: [OperationalError('database is locked')] != []
```

That test passed 3/3 in isolation on this branch and 2/2 with the change
stashed, and the machine was running two concurrent live golden processes at the
time. It is recorded as environmental rather than product, on that evidence.

```
Ran 1144 tests in 58.057s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

Spend: CNY 1.59 across both arms plus one refused launch, against a 6.00 breaker.
