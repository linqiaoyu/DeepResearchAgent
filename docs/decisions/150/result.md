# R150: Evidence-to-report selection contract

## Decision

Reporter now creates one typed pre-writing decision for every planned
sub-question. A sub-question with Evidence selects at most two legal Evidence
IDs; a sub-question without Evidence records an explicit degradation with no
IDs. If the context packer omits every item for an evidenced sub-question, the
decision routes its bounded selection to the existing mechanical evidence
floor rather than pretending the model received it.

The decision is persisted in `ResearchState.report_evidence_selections`, is
part of the Reporter node's declared output contract, and is included in the
Reporter variable input before the model writes. Existing states remain
readable because the new field defaults to an empty list; an empty list does
not pass the F02 guard for a planned report with Evidence.

## Real-artifact proof

The proof uses the untouched R149 Q09 state and report, with both SHA-256
digests published. That real report had Evidence for all three sub-questions
but delivered `sq2_caliber` as an orphan. Its historical state had no
pre-writing decisions, so the new guard rejects it with three missing-decision
failures.

Applying the deterministic selection contract offline to the same real state
produces exactly three decisions for three planned sub-questions, selects only
IDs owned by each sub-question, and reports zero illegal IDs. This does not
claim that selection alone repairs Q09's reader-visible coverage; that is F03.

## Acceptance

- planned sub-questions: 3
- selection decisions: 3
- illegal Evidence IDs: 0
- real report counterexamples rejected: 1
- self-test: 4/4, including missing-decision and invented-ID mutations
- guard wiring: 54/54

No paid provider call or full-cohort run was made.
