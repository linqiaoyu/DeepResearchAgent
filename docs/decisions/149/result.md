# R149: Fresh live loss diagnostic

## Decision

F01 completes its diagnostic objective and remains `INCOMPLETE` against its
original `30/30 status=done` acceptance. The fixed six-shard run produced a
terminal artifact for every frozen question: 28 `done` and two errors. Neither
error was rerun or replaced, and no result from another round was spliced in.
These values are diagnostics over the 28 successful cases, not formal product
metrics:

- `evidence_reachable_rate = 0.614684`
- `orphaned_sub_questions = 1`
- `false_premise_failed = 1`
- funnel totals: 475 retrieved sources, 1,866 extracted Evidence items, 1,526
  packed Evidence items, 216 representative cited Evidence items, and 1,147
  reader-visible Evidence items
- live fidelity: LLM 28/28, retrieval 28/28, structured data 28/28
- full diagnostic cost: CNY 13.70871656

The published machine proof records `formal_product_metrics=false`,
`product_acceptance_status=incomplete`, the 28-case denominator, the merged
artifact digest, and all six ledger digests.

## Preserved failures and repairs

Q13 terminated with `LLMRetryExhaustedError` after three planner attempts hit
the inherited 60-second transport boundary. Q21 terminated with
`FileNotFoundError` when two shard processes competed for the shared global
ledger index temporary path. Both failures remain in the diagnostic proof.

The Harness now gives the planner role an explicit 180-second per-attempt bound
and routes both engine and golden judge accounting through the configured
shard-local ledger as the global budget authority. These changes were validated
without rerunning a golden-set case:

- four concurrent processes completed 4/4 calls using four distinct ledger
  authorities and four distinct index paths; a duplicate-authority negative
  control was rejected;
- three preregistered live planner calls completed 3/3 without fallback under
  the 180-second bound, with three offline-verifiable completed trajectories;
  latency was 44.632434s, 15.993716s, and 15.950994s;
- planner-probe cost was CNY 0.01376744 against the CNY 1 fuse.

The mechanism probes make no finance-quality claim and reran zero golden cases.
The first probe command failed before any provider call because its offline
stub budget was below the client's worst-case reservation and the script called
a nonexistent cleanup method. That command-construction failure was corrected;
it is not counted as a provider or product failure.

## Stage-two execution policy

There is no F01 recovery cohort. F02-F10 may use only the 28 successful R149
reports and states; Q13 and Q21 remain absent. F11 is a fixed 6-10 question live
reliability canary, F13 is conditional on a failed full acceptance, F14 is the
sole planned full 30-question product candidate, and F15 makes no paid provider
calls. Product thresholds, frozen truth, R160 deadline, and the ban on saved
states, best-of selection, and cross-run splicing are unchanged.

## Evidence

- `live-loss-baseline-proof.json`: immutable diagnostic counts and source
  digests.
- `reliability-probe-preregistration.json`: hypothesis, sample rationale,
  decision rule, and CNY 1 fuse registered before paid calls.
- `reliability-probe-proof.json`: ledger and planner mechanism proof.
- `data/stage_two_execution.json`: machine-readable amended execution policy.
- `scripts/check_f01_live_baseline.py`,
  `scripts/check_r149_reliability_probes.py`, and
  `scripts/check_stage_two_execution.py`: falsifiable gate checks.
