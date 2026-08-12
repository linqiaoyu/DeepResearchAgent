# R164 — failed product candidate and authorized Tavily rollover

R164 is a complete failed experiment, not a product proof. The merged artifact
contains all 30 fixed questions exactly once, with 16 `done` and 14 `error`.
All three provider fidelity labels are live and no saved state was used, but
`30/30 status=done` failed; the formal product metrics are therefore not
published from the successful subset.

The root cause is now externally confirmed rather than inferred from Harness
`20/20` messages. Every one of the 148 Tavily calls in the R164 time window
recorded `HTTPStatusError` and zero results. A direct, redacted probe returned
HTTP 432 with usage-limit-exceeded-plan semantics. This is the exact condition
for which the user authorized key replacement. A probe using the replacement
key returned HTTP 200 and a non-empty result, after which the ignored local
`.env` was updated. Neither key value was printed into this decision record,
tracked files, runner output, or report.

Q16 also failed the behavioral criterion because it could only say the premise
was unverified: the exhausted search provider supplied no market-share evidence
from which to state that CATL remained first. This is not treated as a new code
defect before the replacement-key run.

No R164 question will be rerun, replaced, or spliced. The replacement key will
be evaluated only in a newly preregistered independent candidate. R164 spent
CNY 2.67472112, bringing cumulative programme spend to CNY 38.91832338.
