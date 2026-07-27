from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.research_snapshot import (
    ResearchSnapshot,
    SnapshotClaim,
)
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    ResearchState,
    StrictModel,
)
from deepresearch_agent.domains.registry import load_domain_pack

if TYPE_CHECKING:
    from deepresearch_agent.orchestration.decision_context import (
        DecisionContext,
    )

PriorQuestionKind = Literal["verify", "explore", "watch"]


class PriorQuestionClassification(StrictModel):
    sub_question_id: str
    kind: PriorQuestionKind
    criterion: str
    prior_claim_id: str | None = None
    prior_claim_text: str | None = None
    prior_confidence: float | None = Field(default=None, ge=0, le=1)
    prior_as_of: str | None = None
    priority_urls: list[str] = Field(default_factory=list)


def classify_subquestions_from_prior(
    state: ResearchState,
    snapshot: ResearchSnapshot,
    *,
    watch_confidence_threshold: float = 0.7,
    decision_context: DecisionContext | None = None,
) -> list[PriorQuestionClassification]:
    if not state.plan:
        raise ValueError("Prior-memory classification requires a plan")
    classifications: list[PriorQuestionClassification] = []
    for sub_question in state.plan.sub_questions:
        query_text = " ".join(
            [
                sub_question.question,
                *sub_question.search_queries,
            ]
        )
        claim, overlap = _best_claim(query_text, snapshot.claims)
        if claim is None or overlap == 0:
            classification = PriorQuestionClassification(
                sub_question_id=sub_question.id,
                kind="explore",
                criterion=(
                    "no prior claim has lexical overlap with this sub-question"
                ),
                prior_as_of=snapshot.as_of.isoformat(),
            )
        elif (
            claim.confidence < watch_confidence_threshold
            or claim.thesis_direction == "uncertain"
        ):
            classification = PriorQuestionClassification(
                sub_question_id=sub_question.id,
                kind="watch",
                criterion=(
                    "matched prior claim is low-confidence or unverified"
                ),
                prior_claim_id=claim.claim_id,
                prior_claim_text=claim.text,
                prior_confidence=claim.confidence,
                prior_as_of=snapshot.as_of.isoformat(),
            )
        else:
            classification = PriorQuestionClassification(
                sub_question_id=sub_question.id,
                kind="verify",
                criterion=(
                    "matched prior claim is sufficiently confident and must "
                    "be checked for continued validity"
                ),
                prior_claim_id=claim.claim_id,
                prior_claim_text=claim.text,
                prior_confidence=claim.confidence,
                prior_as_of=snapshot.as_of.isoformat(),
                priority_urls=sorted(set(claim.source_urls)),
            )
        classifications.append(classification)
        inputs: dict[str, object] = {
            "sub_question_id": sub_question.id,
            "prior_claim_id": classification.prior_claim_id,
            "prior_claim": classification.prior_claim_text,
            "prior_confidence": classification.prior_confidence,
            "prior_as_of": classification.prior_as_of,
            "priority_urls": classification.priority_urls,
        }
        if decision_context:
            fields = ("iteration", "budget", "unresolved_critic_issues")
            inputs["decision_context_fields"] = list(fields)
            inputs["decision_context"] = decision_context.field_snapshot(
                *fields
            )
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="prior_memory_classification",
                made_by="PlannerAgent",
                inputs=inputs,
                criterion=classification.criterion,
                outcome=classification.kind,
                alternatives_considered=["verify", "explore", "watch"],
            ),
        )
    state.metadata["prior_memory"] = {
        "question_id": snapshot.question_id,
        "as_of": snapshot.as_of.isoformat(),
        "snapshot": snapshot.model_dump(mode="json"),
        "classifications": [
            item.model_dump(mode="json") for item in classifications
        ],
    }
    return classifications


def prior_difference_rows(
    state: ResearchState,
    snapshot: ResearchSnapshot,
) -> list[dict[str, object]]:
    current = {
        key: item
        for item in state.evidence_store
        for key in [numeric_evidence_key(item)]
        if key is not None
    }
    rows: list[dict[str, object]] = []
    for claim in snapshot.claims:
        key = snapshot_claim_key(claim)
        if claim.value is None or key is None:
            rows.append(
                {
                    "claim_id": claim.claim_id,
                    "prior": claim.text,
                    "status": "not_verified",
                    "explanation": "本期没有可按四键核实的数值事实。",
                    "evidence_ids": [],
                }
            )
            continue
        evidence = current.get(key)
        if evidence is None or not evidence.numeric_fields:
            rows.append(
                {
                    "claim_id": claim.claim_id,
                    "prior": claim.text,
                    "status": "not_verified",
                    "explanation": "本期未检索到相同四键事实。",
                    "evidence_ids": [],
                }
            )
            continue
        current_value = evidence.numeric_fields.value
        changed = (
            current_value is not None
            and claim.value is not None
            and current_value != claim.value
        )
        rows.append(
            {
                "claim_id": claim.claim_id,
                "prior": claim.text,
                "status": "changed" if changed else "verified_unchanged",
                "explanation": (
                    f"上期={claim.value}{claim.unit or ''}，"
                    f"本期={current_value}{evidence.numeric_fields.unit or ''}。"
                ),
                "evidence_ids": [evidence.id],
            }
        )
    return rows


def numeric_evidence_key(
    evidence: Evidence,
) -> tuple[str, str, str, str] | None:
    fields = evidence.numeric_fields
    if (
        fields is None
        or not fields.entity
        or not fields.metric_name
        or not fields.period
    ):
        return None
    return (
        _normalize(fields.entity),
        _normalize(fields.metric_name),
        _normalize(fields.period),
        _normalize(fields.dimension),
    )


def snapshot_claim_key(
    claim: SnapshotClaim,
) -> tuple[str, str, str, str] | None:
    if not claim.key.entity or not claim.key.metric or not claim.key.period:
        return None
    return (
        _normalize(claim.key.entity),
        _normalize(claim.key.metric),
        _normalize(claim.key.period),
        _normalize(claim.key.scope),
    )


def evidence_explains_change(evidence: Evidence) -> bool:
    text = f"{evidence.claim} {evidence.extract_text}".lower()
    return any(term in text for term in ("because", "due to", "increase", "decrease", "changed")) or load_domain_pack("finance").evidence_explains_change(text)


def _best_claim(
    query: str,
    claims: list[SnapshotClaim],
) -> tuple[SnapshotClaim | None, int]:
    query_tokens = _tokens(query)
    ranked = sorted(
        (
            (len(query_tokens & _tokens(claim.text)), claim.claim_id, claim)
            for claim in claims
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if not ranked:
        return None, 0
    return ranked[0][2], ranked[0][0]


def _tokens(text: str) -> set[str]:
    return {
        item.lower()
        for item in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)
    }


def _normalize(value: str) -> str:
    return "".join(
        item.lower()
        for item in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", value)
    )
