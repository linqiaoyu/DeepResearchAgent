# R162 — post-fix full candidate

## Decision

**PRODUCT ACCEPTANCE FAILED.** The frozen Q01-Q30 cohort produced 30 exact-once
terminal records with three live provider layers and no saved states, reruns or
splicing. Only 11 cases completed; 19 ended `budget_exceeded`, so this candidate
cannot be proof and no product metric is published from the successful subset.

## Newly exposed failure classes

1. Within each question, parallel research branches correctly share one
   20-search run allowance. When the allowance refused a request, a branch with
   no *branch-local* sources re-raised the exception. That unwound the whole
   graph even when sibling branches already held evidence. The repair must make
   the empty branch degrade explicitly and let `research_join` preserve the
   aggregate work; the 20-search hard limit remains unchanged.
2. Q16's delivered report explicitly says 宁德时代 remained first and was not
   overtaken. The behavioral evaluator nevertheless marked it as asserting the
   false premise because the same long summary line later discussed *revenue*
   decline and its causes. Assertion detection must operate on the relevant
   relation/clause, not treat any decline-cause text on a refuting line as the
   question's overtaking premise.

These are new downstream paths exposed only after R161 made the report refute
the premise and the full runner exercised multiple cases per shard. Neither is
a Tavily account quota error; the replacement key was not used.

## Cost and boundaries

Ledger cost was CNY 3.32336636, bringing cumulative plan spend to CNY
36.24360226, far below the CNY 300 fuse. This result is immutable, cannot be
spliced, and will not be supplemented by rerunning its failures on unchanged
code. Both classes route to a code repair before another independently
preregistered full candidate.
