# R161 — conditional F13 premise-aware reporting

## Decision

PASS for the targeted defect class; **product acceptance remains incomplete**.
The Reporter now receives an explicit premise assessment derived only from its
preselected Evidence. When finance evidence establishes the opposite relation,
the model is instructed to reject the topic premise and the Harness enforces
the same rule after generation: positively adopting the contradicted premise is
removed and a cited correction is inserted before key findings.

The relationship detector belongs to `FinanceDomainPack`. The generic Reporter
consumes only a neutral `PremiseAssessment`; core finance imports remain zero and
the domain literal ratchet decreased rather than grew. Neutral domain defaults
return `unresolved`, so no new domain is implied or fabricated refutation added.

## Evidence

- The reduced real R160 Q16 failure changes from `refute_premise=false` to
  `true` using its original selected Evidence IDs and claims.
- The existing Q08/Q16 behavioral suite remains green.
- A simulated Reporter draft that still asserts the false relation is filtered
  and corrected; the prompt payload independently contains the assessment.
- An inconclusive true-ranking topic is unchanged.
- Bypassing the assertion filter and refuting an unresolved topic both fail the
  new guard; raw failures are published beside this record.

No paid provider call, full cohort run, saved-state product proof, golden change,
threshold change or remote write occurred. A later full 30-question run must be
preregistered and independently prove the product metrics on this new code.
