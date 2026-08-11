# 121 result

R120 found the research loop could not iterate: with `RESEARCH_LOOP_ENABLED=true`
and `max_iterations=2`, no refinement pass ran on either question, because the
first pass was sized to spend the loop's whole budget. This round fixed the
sizing. The loop now iterates. It still does not demonstrably help.

## The fix

`BranchBudget.allocate` handed out `min(total_budget, per_branch_cap * n)`, and
`reallocate` draws from `total_budget - total_used`. So a first pass sized to
spend the pool left nothing, and the loop stopped at its ceiling or under the
20% remaining-budget threshold.

`BranchBudget` now carries `planned_iterations`, and the initial allocation
takes `total_budget // planned_iterations` -- a pool that must cover N
iterations may not be spent by the first. The share is floored at the branch
count so no branch is allocated nothing.

| `planned_iterations` | allocation over 4 branches, pool 20 |
|---:|---|
| 1 | 5/5/5/5 (20) |
| 2 | 3/3/2/2 (10) |
| 3 | 2/2/1/1 (6) |

`planned_iterations` is 1 unless the loop is active, so the shipped default path
is byte-identical.

## What the live run shows

| run | Q | evidence | research passes | gold in evidence | gold in report |
|---|---|---:|---:|---:|---:|
| R120 arm A, loop off | Q13 | 61 | 0 | 1/2 | 1/2 |
| R120 arm A, loop off | Q16 | 152 | 0 | 4/4 | 1/4 |
| R120 arm B, loop on, pre-fix | Q13 | 156 | 1 | 1/2 | 1/2 |
| R120 arm B, loop on, pre-fix | Q16 | 161 | 1 | 4/4 | 3/4 |
| **R121, loop on, fixed** | **Q13** | 47 | **2** | 1/2 | 1/2 |
| **R121, loop on, fixed** | Q16 | 130 | 1 | 4/4 | 2/4 |

`research_refine` appears in the run log for the first time. Q13 executed two
research passes where every previous configuration executed one.

**And the second pass retrieved no additional gold fact.** Q13 stays at 1/2 in
evidence and 1/2 in the report. Q16 still ran a single pass.

Cost was CNY 0.35 against a 5.00 breaker, lower than R120's arm B, which is
run-to-run variation rather than an effect of this change.

## The default stays closed

R120's rule, fixed before spending, required strictly more gold tokens on both
questions. This run retrieved the same tokens as every other arm. One live
sample per question cannot separate a code effect from the run-to-run variation
R118 measured, and the effect here is zero, not small.

So the loop is now **mechanically able** to iterate and **not yet shown to be
worth iterating**. Those are different claims and this round only supports the
first.

## Why there is no end-to-end test for this

An engine-level test in fixture mode was written and deleted. Forcing
`planned_iterations` back to 1 -- the behaviour R120 measured stopping the loop
dead -- still produced two research passes, because a fixture branch is
satisfied in fewer calls than either allocation grants, so the allocation never
binds. It passed for both implementations, which makes it evidence of nothing;
shipping it would have been R109's fixture-instrument mistake again.

The allocation arithmetic is tested where it discriminates (5 cases, including
a share smaller than the branch count and a rejected `planned_iterations=0`).
The end-to-end claim rests on the live run above.

## Gate

```
Ran 1149 tests in 58.650s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

## Not established

- **That iterating improves the answer.** Two questions, one sample, zero
  measured gain. Deciding this needs a question set where the first pass leaves
  a gap a second pass could close, and R119 removed the clearest such cases by
  fixing the budget termination that emptied them.
- **Why Q16 still runs one pass.** Its first pass either exhausted its share or
  reported no actionable gap; this round did not chase it.
