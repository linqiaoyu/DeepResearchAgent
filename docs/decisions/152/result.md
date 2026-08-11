# R152 — F04 False-premise behavior repair

Status: COMPLETE

## Decision

`refute_premise` now accepts either a complete contradicting numeric fact or an
explicit evidence-cited semantic denial grounded in the frozen fact's scope.
It rejects the report first if assertive body prose adopts the false premise.
Question headings, conditional statements, and questions are not assertions.

The registry no longer uses constructed positive reports. Each frozen
false-premise question has a two-sided real-run pair: R113 is rejected and R149
is accepted. The guard requires this per question and rejects constructed
provenance when `require_real_discrimination` is set.

## Evidence

- Registered false-premise questions: 2.
- Real accepted reports: 2.
- Real rejected reports: 2.
- Verdict mismatches: 0.
- False-premise assertions in accepted reports: 0.
- A mutation changing R149 Q16 from “并未反超” to “已经反超” failed the guard.

Proof: `false-premise-proof.json`.

## Capability decision

`SKILL_PACKS_ENABLED` reached its R152 deadline and is permanent `opt_in`.
Its H2 runtime proof is valid, but the registered 30-case paired finance
improvement has not been measured. R149 bypassed Skills, so it supplies no
default-on evidence. No deferral or unsupported graduation was used.

No paid provider call was made. No full-cohort product run was started.
