from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from deepresearch_agent.capability_rules import DEFAULT_CAPABILITY_RULES
from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.schemas import (
    AgentDecision,
    ResearchState,
    StrictModel,
    SubQuestion,
)
from deepresearch_agent.tools.capability_registry import (
    CapabilityRegistry,
)

FIXED_CAPABILITY_SET = (
    "disclosure_source",
    "web_search",
    "web_fetch",
    "structured_data_provider",
)


class CapabilitySelection(StrictModel):
    sub_question_id: str
    sub_question_type: str
    candidate_capabilities: tuple[str, ...]
    selected_capabilities: tuple[str, ...]
    rejected_capabilities: tuple[str, ...]
    criterion: str
    fallback: bool = False


class DeterministicCapabilitySelector:
    """Select registered capabilities with explicit deterministic rules."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        rules: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.registry = registry
        self.rules = {
            str(question_type): tuple(str(name) for name in names)
            for question_type, names in (
                DEFAULT_CAPABILITY_RULES
                if rules is None
                else rules
            ).items()
        }

    @classmethod
    def from_json(
        cls,
        registry: CapabilityRegistry,
        payload: str,
    ) -> DeterministicCapabilitySelector:
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "dynamic capability rules must be valid JSON"
            ) from exc
        if not isinstance(raw, dict) or not all(
            isinstance(key, str)
            and isinstance(value, list)
            and all(isinstance(item, str) for item in value)
            for key, value in raw.items()
        ):
            raise ValueError(
                "dynamic capability rules must map strings to string lists"
            )
        return cls(registry, raw)

    def select(
        self,
        state: ResearchState,
        sub_question: SubQuestion,
    ) -> CapabilitySelection:
        question_type = classify_subquestion(sub_question)
        candidates = tuple(
            item.name for item in self.registry.query()
        )
        configured = self.rules.get(question_type)
        selected = tuple(
            name
            for name in (configured or ())
            if name in candidates
            and _is_applicable(
                self.registry,
                name,
                question_type,
            )
        )
        if "disclosure_source" in selected and not _has_security_identity(
            sub_question
        ):
            selected = tuple(
                name for name in selected if name != "disclosure_source"
            )
        fallback = configured is None or not selected
        if fallback:
            selected = tuple(
                name
                for name in FIXED_CAPABILITY_SET
                if name in candidates
            )
            criterion = (
                f"no usable rule matched type={question_type}; "
                "fall back to the 015 fixed capability set"
            )
        else:
            criterion = (
                f"apply configured rule for type={question_type} and keep "
                "only capabilities declared applicable by the registry; "
                + (
                    "disclosure_source is prioritized because a security "
                    "code or company entity is identifiable; "
                    if "disclosure_source" in selected
                    else ""
                )
                + (
                    "web_fetch is required to read first-party disclosure "
                    "text for financial or event verification"
                    if "web_fetch" in selected
                    else "web_fetch is rejected because this branch has no "
                    "financial, event, or explicit verification intent"
                )
            )
        rejected = tuple(
            name for name in candidates if name not in selected
        )
        selection = CapabilitySelection(
            sub_question_id=sub_question.id,
            sub_question_type=question_type,
            candidate_capabilities=candidates,
            selected_capabilities=selected,
            rejected_capabilities=rejected,
            criterion=criterion,
            fallback=fallback,
        )
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="capability_selection",
                made_by="ResearcherAgent",
                inputs={
                    "sub_question_id": sub_question.id,
                    "sub_question_type": question_type,
                    "candidate_capabilities": list(candidates),
                    "selected_capabilities": list(selected),
                    "rejected_capabilities": list(rejected),
                    "fallback": fallback,
                },
                criterion=criterion,
                outcome=f"selected={list(selected)}",
                alternatives_considered=list(candidates),
            ),
        )
        return selection


def classify_subquestion(sub_question: SubQuestion) -> str:
    capabilities = {
        request.capability
        for request in sub_question.structured_data_requests
    }
    if "price_history" in capabilities:
        return "market_price"
    if capabilities.intersection(
        {"financial_indicators", "symbol_resolve"}
    ):
        return "financial_metric"
    joined = " ".join(
        [
            sub_question.id,
            sub_question.question,
            *sub_question.search_queries,
        ]
    ).lower()
    if any(term in joined for term in ("verify", "核实", "验证")):
        return "verify"
    if any(
        term in joined
        for term in (
            "event",
            "timeline",
            "公告",
            "开工",
            "投产",
            "时间线",
            "事件",
            "交易",
            "建设进展",
        )
    ):
        return "event"
    return "narrative"


def _has_security_identity(sub_question: SubQuestion) -> bool:
    joined = " ".join(
        [sub_question.question, *sub_question.search_queries]
    )
    return bool(re.search(r"(?<!\d)\d{6}(?!\d)", joined)) or any(
        request.symbol or request.company_name
        for request in sub_question.structured_data_requests
    ) or "宁德时代" in joined


def _is_applicable(
    registry: CapabilityRegistry,
    name: str,
    subquestion_type: str,
) -> bool:
    metadata = registry.get(name)
    return (
        "*" in metadata.applicable_subquestion_types
        or subquestion_type in metadata.applicable_subquestion_types
    )
