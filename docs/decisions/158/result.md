# R158 — F11 live reliability canary

## Decision

F11 is **RELIABILITY FAILED** and routes one defect class to F12. The fixed
eight-question canary ran exactly once with no saved states and produced eight
terminal outer artifacts, but the underlying Q13 workflow terminated
`budget_exceeded` during Critic retry fan-out. The golden runner nevertheless
published Q13 as `status=done`; this terminal-status mismatch is preserved as a
second integrity symptom of the same failed run and must not be hidden by the
outer result.

This canary is not product acceptance, does not publish formal product metrics,
does not prove any capability effective, and cannot contribute cases or scores
to F14.

## Measured outcome

- Fixed cohort: Q01, Q06, Q09, Q13, Q16, Q21, Q28, Q30; exact coverage 8/8.
- Three configured provider layers reported live fidelity for 8/8 cases.
- Underlying workflow termination: 7 completed, 1 budget exceeded (Q13).
- Planner timeouts: 0. Q13 planner latency was 22.021 seconds; the largest
  canary planner latency was Q21 at 40.356 seconds, below the explicit
  180-second contract.
- Shared-ledger collisions: 0. The two concurrently running shards used
  distinct ledger authorities and both exited normally.
- Silent exclusions: 0. Failed-case reruns, best-of selection and saved-state
  reuse: 0.
- State, trajectory and manifest locators: 8/8.
- Measured two-ledger cost: CNY 4.61891248, below the preregistered CNY 12
  round fuse. Cumulative plan spend after R158 is CNY 18.36053498.

## Failure class routed to F12

Q13 reached the run-wide Tavily search ceiling during concurrent Critic retry
fan-out: `20/20`, with three rejected search attempts. Its trajectory correctly
ended `budget_exceeded`, while the outer evaluation record called the case
`done` and continued citation/judge evaluation. F12 must address this as the
class **budget-aware Critic retry scheduling and terminal-status integrity**:

1. Critic retry fan-out must not schedule more external search work than the
   remaining run-wide request budget can authorize.
2. A non-completed workflow terminal state must never be converted to an outer
   `done` result merely because a degraded report exists.

The Q06 Web fetch timeout remained an explicit degraded tool event and the
workflow completed; it is not a planner timeout or a separate hard-failure
class. No canary question will be rerun to improve this historical result.

## Evidence

- `preregistration.json` freezes the cohort, shards, hypotheses and fuses.
- `live-canary-proof.json` stores hashes and content-free summaries for the
  ignored merged result, two ledgers, and every state/trajectory/manifest.
- `scripts/check_f11_live_canary.py --self-test` verifies the historical failure
  and the non-product boundary.
- `mutation-hide-q13-failure.txt` and `mutation-product-overclaim.txt` preserve
  real negative-control failures.
