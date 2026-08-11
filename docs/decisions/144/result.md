# R144: Observability and replay H2

New v7 trajectories commit to the complete request, call/event sequence,
termination, and artifacts. Deleting a call or changing a prompt fails closed.
Completed trajectories retain strict byte-level report replay; failed and
budget-exceeded trajectories expose a separate offline-verification result and
do not claim semantic replay. Legacy v3-v6 validation remains supported.

The capability activity vocabulary now distinguishes `ran`, `active`,
`bypassed`, `degraded`, and `failed`. Harness technology locator coverage is
12/12.
