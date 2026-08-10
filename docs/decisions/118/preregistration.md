# 118 preregistration (written before the paid run)

Authorised by the standing `/goal` instruction: 付费验证直接批准.

## Hypothesis

R116 and R117 were validated by counterfactual — the shipped code called with
the 30 saved R113 states' own inputs. That proves what the code does to those
states. It does not prove the delivered product changed, and AGENTS.md §7 is
explicit that a run after a code change is a new experiment.

Predicted, on a live run of the same questions:

| metric | R113 live (delivered) | predicted |
|---|---|---|
| orphaned sub-questions | 8/80 | **0** |
| never-cited reference lines | 83% | **0** |
| provider-series reference lines | 969 total | order of magnitude fewer |
| `false_premise_failed` (Q08, Q16) | 2/2 | ≤ 1/2 |

## Measurement

Deterministic, no judge, so no noise floor is required:

- `scripts/check_evidence_reaches_reader.py --state <state.json>`
- `scripts/check_reference_list_hygiene.py --report <report.md>`
- `deepresearch_agent.evaluation.false_premise_failed` against frozen gold
- reference lines / body lines counted from the delivered markdown

## Questions

A preregistered subset, not the full 30. Chosen before running, for what each
predicts:

| id | why |
|---|---|
| Q08 | false premise; the counterfactual flipped it to refuted |
| Q16 | false premise; the counterfactual surfaced a cited contradiction |
| Q25 | 118 reference lines, 4 cited |
| Q30 | 766 lines, 736 references, 3 cited — the worst case measured |

Reported as a 4-question subset. No score from it may be compared to any
30-question round.

## Budget and circuit breakers

- per question: CNY 1.50 research + judge (R113 median was 0.23, max 0.65)
- whole round: **CNY 8.00**; stop on breach and report what completed
- judge samples: 1 (this round measures deterministic properties, not scores)
- wall clock: abandon a question exceeding 45 minutes

## Decision rule

- All four deterministic predictions hold → R116/R117 confirmed in production.
- Any prediction fails → report the failure with the delivered artifact, do not
  re-run to get a better one (§7 forbids picking the best of repeated runs on
  identical code).

## Rollback

`git revert` of b7a4841 (R117) and 70a5a4f (R116). Neither changes stored data,
so rollback is code-only.
