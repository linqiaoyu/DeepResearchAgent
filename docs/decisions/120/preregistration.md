# 120 preregistration (written before the paid run)

Authorised by the standing `/goal` instruction: 付费验证直接批准.

## Question

Does opening the research loop change what the agent retrieves and reports?

R120 already changed the loop's continue condition so it no longer iterates on
`freshness`, which is unclosable for a past fiscal year (28 sub-questions, the
freshest evidence a median 471 days old). That moved the questions the loop
would iterate on from 28/30 to 25/30. It does not tell us whether iterating
helps.

## Arms

Same questions, same code, same evaluation clock; one setting differs.

| arm | setting |
|---|---|
| A (control) | shipped default: `RESEARCH_LOOP_ENABLED=false` |
| B | `RESEARCH_LOOP_ENABLED=true`, `RESEARCH_LOOP_MAX_ITERATIONS=2` |

Questions: **Q13** and **Q16**. Both retrieved abundant evidence in R113 (142
and 155 items) and still missed gold facts, so refinement has material to work
with; neither is one of the budget-starved questions R119 fixed.

## Measurement

Deterministic only:

- gold numeric tokens present in the evidence store
- gold numeric tokens present in the delivered report
- research-loop iterations actually executed (`research_loop_tracker`)
- cost and latency per question

## Noise floor, stated before the result

n=1 per arm per question. R118 established that a single live run cannot
separate a code effect from run-to-run variation: the same question on
near-identical code returned `false_premise_failed` False once and True once.

Therefore, declared in advance:

- A difference of **fewer than 2 gold tokens** per question will be reported as
  **within noise, no conclusion**.
- The loop's default will be flipped **only** if arm B retrieves strictly more
  gold tokens on both questions *and* the iterations actually ran. Otherwise the
  default stays closed and the round says so.

## Budget

- per question per arm: CNY 1.50
- whole experiment: **CNY 6.00**, stop on breach
- abandon any question exceeding 45 minutes

## Rollback

The gap classification is independent of the flip and stays either way.
`git revert` of the flip commit alone if it ships and regresses.
