"""Domain-neutral reporting contract for evidence-derived premise checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PremiseAssessment:
    status: str
    premise_kind: str
    evidence_ids: tuple[str, ...]
    correction_claims: tuple[str, ...]
    reason: str

    def prompt_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "premise_kind": self.premise_kind,
            "evidence_ids": list(self.evidence_ids),
            "correction_claims": list(self.correction_claims),
            "reason": self.reason,
        }


def unresolved_premise() -> PremiseAssessment:
    return PremiseAssessment(
        status="unresolved",
        premise_kind="none",
        evidence_ids=(),
        correction_claims=(),
        reason="selected evidence does not establish a premise contradiction",
    )
