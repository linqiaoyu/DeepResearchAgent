# Stage-two execution amendment

The user amended the approved stage-two execution policy while the preregistered
R149 shards were already running. The running shards continue to terminal state;
no failed case is rerun or replaced.

- F01 is a real loss diagnostic. Its diagnostic objective completes when all 30
  fixed cases have a terminal artifact, but its `30/30 status=done` acceptance
  remains `INCOMPLETE`. Metrics are labelled with the successful-case
  denominator and are not formal product metrics. Q13 and Q21 remain failures.
- The planner-timeout and shared-ledger defects receive bounded mechanism probes,
  not another 30-case F01 run. Those probes cannot support a finance-quality
  claim.
- F02-F10 continue using only the successful R149 reports and states. Missing
  Q13/Q21 data may not be spliced from another run.
- F11 becomes one preregistered fixed 6-10 case live canary. It validates the
  default combination, three live boundaries, accounting, trajectory, fidelity,
  evidence funnel and the absence of the two R149 reliability failures. It does
  not publish formal product metrics or contribute to F14.
- F13 is conditional. It runs defect-class repair only after a failed full
  product acceptance; it does not schedule a routine full-cohort rerun.
- F14 is the sole planned 30-case, three-layer-live product run. A passing first
  candidate proceeds directly to F15. A failed candidate is preserved whole;
  only new code may produce the next independent 30-case candidate, with no
  cross-run splicing.
- F15 performs no paid provider calls. It closes local gate, Postgres/Qdrant
  service CI, product acceptance, configuration and decision records.

The product thresholds, frozen cohort, golden truth, target R160, and prohibition
on saved-state, best-of and cross-run proof assembly are unchanged.
