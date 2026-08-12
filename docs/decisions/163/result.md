# R163 — conditional F13 aggregate budget and premise repairs

## Decision

PASS for the R162 failure classes; **product acceptance remains incomplete**.
No product metric is claimed from targeted or archived data.

The external request ceiling remains 20 and remains run-wide. An exhausted
parallel branch now returns an explicit degradation record instead of unwinding
the graph. At `research_join`, exhaustion terminates the run only when every
branch and structured-data path produced zero research output; that terminal
state retains its partial report and strict replay semantics.

The Q16 behavioral scorer now distinguishes the frozen false relation
(`被比亚迪反超`) from unrelated later statements such as revenue decline. The
reduced real R162 Q16 report is permanently registered as an accepted real-run
fixture, while the real R113/R160 positive assertion remains rejected.

R162 Q08 exposed a second evidence loss in the same false-premise class. Its
primary annual report contained the verbatim statement `营业总收入 ... 同比增长
15.66%`, but extraction retained only the later attribution sentence. A narrow
finance-domain authoritative parser now backfills that disclosed value and
direction. It does not infer missing comparisons and accepts only an eligible
primary annual report. `营业总收入` is also normalized to the existing
`营业收入` metric at the finance vocabulary boundary.

## Verification

- 1,232 tests passed; 7 registered service skips.
- Behavioral registry self-test rejects always-true and always-false mutations.
- The real R162 Q16 excerpt passes; the real R113 positive premise assertion
  still fails.
- A first-request refusal in one branch degrades locally; aggregate zero output
  still produces `budget_exceeded` and strict replay succeeds.
- The reduced R162 Q08 annual-report sentence produces typed 2024 revenue
  Evidence with `1741.44 亿元` and `同比增长15.66%`.

No paid provider call, saved-state product proof, golden change, threshold
change or remote write occurred. The next full 30-question run must be a newly
preregistered independent acceptance candidate.
