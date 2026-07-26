from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import Field

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm.client import BudgetExceededError, CostOverrunError
from deepresearch_agent.schemas import Evidence, ResearchState, StrictModel
from deepresearch_agent.settings import project_root
from deepresearch_agent.trajectory import TrajectoryCacheMissError


_DECISION_SECTION_RE = re.compile(
    r"(?ms)^## (?:Agent 决策记录|决策链)\s*$.*?(?=^## |\Z)"
)
_EXPERIMENT_TERMS = (
    "Reflector",
    "REFLECTION_ENABLED",
    "reflection_result",
    "reflector_placeholder",
    "made_by",
    "experimental_arm",
    "treatment_arm",
    "control_arm",
    "实验组",
    "对照组",
)
DEFAULT_EVIDENCE_MAX_ITEMS = 80
DEFAULT_EVIDENCE_TOKEN_BUDGET = 12_000


class SemanticJudgeScore(StrictModel):
    """Semantic-only scores; financial-number correctness is out of scope."""

    answer_completeness: float = Field(ge=0, le=1)
    answer_completeness_reason: str = Field(min_length=1)
    answer_relevance: float = Field(ge=0, le=1)
    answer_relevance_reason: str = Field(min_length=1)
    answer_shape: float = Field(ge=0, le=1)
    answer_shape_reason: str = Field(min_length=1)
    citation_support: float = Field(ge=0, le=1)
    citation_support_reason: str = Field(min_length=1)
    faithfulness: float = Field(ge=0, le=1)
    faithfulness_reason: str = Field(min_length=1)


class SemanticJudgeFailure(RuntimeError):
    """A semantic score could not be produced; no score may be inferred."""

    def __init__(self, error_type: str) -> None:
        super().__init__(f"semantic judge failed: {error_type}")
        self.error_type = error_type


class SemanticJudge(Protocol):
    def score(self, state: ResearchState) -> SemanticJudgeScore:
        """Score report semantics without judging exact numeric correctness."""


class RuntimeSemanticJudge:
    """Optional typed runtime judge routed through the shared LLM client."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        evidence_max_items: int = DEFAULT_EVIDENCE_MAX_ITEMS,
        evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
    ) -> None:
        if evidence_max_items < 1:
            raise ValueError("evidence_max_items must be at least 1")
        if evidence_token_budget < 1:
            raise ValueError("evidence_token_budget must be at least 1")
        self.llm_client = llm_client
        self.evidence_max_items = evidence_max_items
        self.evidence_token_budget = evidence_token_budget
        self.prompt = (
            project_root() / "prompts" / "semantic_judge.md"
        ).read_text(encoding="utf-8")

    def score(self, state: ResearchState) -> SemanticJudgeScore:
        evidence, evidence_budget = _bounded_evidence_payload(
            state,
            max_items=self.evidence_max_items,
            token_budget=self.evidence_token_budget,
        )
        payload = {
            "topic": state.topic,
            "research_plan": (
                state.plan.model_dump(mode="json") if state.plan else None
            ),
            "report": _redact_semantic_report(state.final_report or ""),
            "report_footnote_evidence": {
                str(number): evidence_id
                for number, evidence_id in sorted(
                    state.report_footnote_evidence.items()
                )
            },
            "evidence": evidence,
            "evidence_budget": evidence_budget,
        }
        try:
            result = self.llm_client.complete(
                role="judge",
                run_id=state.research_id,
                schema=SemanticJudgeScore,
                messages=[
                    {"role": "system", "content": self.prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            )
        except (BudgetExceededError, CostOverrunError):
            # Budget safety is a run-level invariant, not an optional metric
            # failure, so the engine must retain its existing terminal path.
            raise
        except TrajectoryCacheMissError:
            # Strict replay misses are contract failures, not optional judge
            # degradation, and must remain visible to the replay caller.
            raise
        except Exception as exc:
            raise SemanticJudgeFailure(type(exc).__name__) from exc
        if not isinstance(result.parsed, SemanticJudgeScore):
            raise SemanticJudgeFailure("invalid_typed_output")
        return result.parsed


def _evidence_payload(evidence: Evidence) -> dict[str, object]:
    numeric_fields = (
        evidence.numeric_fields.model_dump(mode="json")
        if evidence.numeric_fields
        else None
    )
    structured_record = (
        evidence.structured_record.model_dump(mode="json")
        if evidence.structured_record
        else None
    )
    return {
        "id": evidence.id,
        "sub_question_id": evidence.sub_question_id,
        "claim": evidence.claim[:2_000],
        "claim_type": evidence.claim_type,
        "source_url": evidence.source_url,
        "source_title": evidence.source_title,
        "source_page": evidence.source_page,
        "source_tier": evidence.source_tier,
        "extract_text": evidence.extract_text[:4_000],
        "numeric_fields": numeric_fields,
        "structured_record": structured_record,
    }


def _bounded_evidence_payload(
    state: ResearchState,
    *,
    max_items: int,
    token_budget: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    evidence_by_id = {item.id: item for item in state.evidence_store}
    mapped_ids = list(
        dict.fromkeys(
            evidence_id
            for _, evidence_id in sorted(
                state.report_footnote_evidence.items()
            )
        )
    )
    ordered_ids = [
        *mapped_ids,
        *(
            item.id
            for item in state.evidence_store
            if item.id not in mapped_ids
        ),
    ]
    included: list[dict[str, object]] = []
    for evidence_id in ordered_ids:
        if len(included) >= max_items:
            break
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        candidate = [*included, _evidence_payload(evidence)]
        if _estimated_json_tokens(candidate) > token_budget:
            continue
        included = candidate
    included_ids = [str(item["id"]) for item in included]
    estimated_tokens = _estimated_json_tokens(included)
    return included, {
        "total_count": len(state.evidence_store),
        "included_count": len(included),
        "omitted_count": max(0, len(state.evidence_store) - len(included)),
        "max_items": max_items,
        "token_budget": token_budget,
        "estimated_tokens": estimated_tokens,
        "included_evidence_ids": included_ids,
        "mapped_evidence_omitted": [
            evidence_id
            for evidence_id in mapped_ids
            if evidence_id not in included_ids
        ],
    }


def _estimated_json_tokens(payload: object) -> int:
    if payload == []:
        return 0
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return max(1, (len(encoded) + 3) // 4)


def _redact_semantic_report(report: str) -> str:
    """Blind semantic scoring to experiment-arm metadata."""

    cleaned = _DECISION_SECTION_RE.sub("", report)
    for term in _EXPERIMENT_TERMS:
        cleaned = re.sub(
            re.escape(term),
            "[CONDITION_REDACTED]",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip()
