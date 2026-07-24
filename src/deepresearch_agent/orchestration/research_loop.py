from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import Field

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    ResearchState,
    StrictModel,
)

if TYPE_CHECKING:
    from deepresearch_agent.orchestration.decision_context import (
        DecisionContext,
    )

COUNTERARGUMENT_TERMS = {
    "risk",
    "constraint",
    "however",
    "compliance",
    "监管",
    "限制",
    "风险",
    "反方",
}


class SufficiencyThresholds(StrictModel):
    min_evidence_count: int = Field(default=2, ge=0)
    min_independent_domains: int = Field(default=2, ge=0)
    min_average_confidence: float = Field(default=0.7, ge=0, le=1)
    max_freshness_age_days: int = Field(default=365, ge=0)
    max_unresolved_critic_issues: int = Field(default=0, ge=0)
    require_counterargument: bool = True


class SubquestionSufficiency(StrictModel):
    sub_question_id: str
    evidence_count: int = Field(ge=0)
    independent_source_domains: int = Field(ge=0)
    average_confidence: float = Field(ge=0, le=1)
    freshest_evidence_age_days: int | None = Field(default=None, ge=0)
    unresolved_critic_issues: int = Field(ge=0)
    missing_counterargument: bool
    sufficient: bool
    gaps: list[str] = Field(default_factory=list)


class ResearchSufficiency(StrictModel):
    score: float = Field(ge=0, le=1)
    sufficient: bool
    by_sub_question: list[SubquestionSufficiency] = Field(
        default_factory=list
    )


def evaluate_research_sufficiency(
    state: ResearchState,
    *,
    as_of: date,
    thresholds: SufficiencyThresholds,
) -> ResearchSufficiency:
    if not state.plan:
        return ResearchSufficiency(score=0.0, sufficient=False)
    issue_counts = _issue_counts(state)
    metrics: list[SubquestionSufficiency] = []
    component_scores: list[float] = []
    for sub_question in state.plan.sub_questions:
        evidence = [
            item
            for item in state.evidence_store
            if item.sub_question_id == sub_question.id
        ]
        evidence_count = len(evidence)
        domains = {_source_domain(item) for item in evidence}
        domains.discard("")
        average_confidence = (
            sum(item.confidence for item in evidence) / evidence_count
            if evidence_count
            else 0.0
        )
        freshest_age = (
            min(max(0, (as_of - item.source_pub_date).days) for item in evidence)
            if evidence
            else None
        )
        missing_counterargument = not _has_counterargument(evidence)
        unresolved = issue_counts.get(sub_question.id, 0)
        gaps: list[str] = []
        if evidence_count < thresholds.min_evidence_count:
            gaps.append("evidence_count")
        if len(domains) < thresholds.min_independent_domains:
            gaps.append("independent_source_domains")
        if average_confidence < thresholds.min_average_confidence:
            gaps.append("average_confidence")
        if (
            freshest_age is None
            or freshest_age > thresholds.max_freshness_age_days
        ):
            gaps.append("freshness")
        if unresolved > thresholds.max_unresolved_critic_issues:
            gaps.append("unresolved_critic_issues")
        if thresholds.require_counterargument and missing_counterargument:
            gaps.append("counterargument")
        metrics.append(
            SubquestionSufficiency(
                sub_question_id=sub_question.id,
                evidence_count=evidence_count,
                independent_source_domains=len(domains),
                average_confidence=round(average_confidence, 6),
                freshest_evidence_age_days=freshest_age,
                unresolved_critic_issues=unresolved,
                missing_counterargument=missing_counterargument,
                sufficient=not gaps,
                gaps=gaps,
            )
        )
        component_scores.extend(
            [
                _ratio(evidence_count, thresholds.min_evidence_count),
                _ratio(
                    len(domains),
                    thresholds.min_independent_domains,
                ),
                _ratio(
                    average_confidence,
                    thresholds.min_average_confidence,
                ),
                (
                    1.0
                    if freshest_age is not None
                    and freshest_age <= thresholds.max_freshness_age_days
                    else 0.0
                ),
                (
                    1.0
                    if unresolved <= thresholds.max_unresolved_critic_issues
                    else 0.0
                ),
                (
                    1.0
                    if not thresholds.require_counterargument
                    or not missing_counterargument
                    else 0.0
                ),
            ]
        )
    score = (
        sum(component_scores) / len(component_scores)
        if component_scores
        else 0.0
    )
    return ResearchSufficiency(
        score=round(score, 6),
        sufficient=bool(metrics) and all(item.sufficient for item in metrics),
        by_sub_question=metrics,
    )


def refine_research_plan(
    state: ResearchState,
    sufficiency: ResearchSufficiency,
    *,
    as_of: date,
    iteration: int,
    decision_context: DecisionContext | None = None,
) -> dict[str, list[str]]:
    if not state.plan:
        raise ValueError("Research re-planning requires an existing plan")
    metrics_by_id = {
        item.sub_question_id: item
        for item in sufficiency.by_sub_question
    }
    refined: dict[str, list[str]] = {}
    gaps_by_id: dict[str, list[str]] = {}
    for sub_question in state.plan.sub_questions:
        metrics = metrics_by_id[sub_question.id]
        gaps_by_id[sub_question.id] = list(metrics.gaps)
        queries: list[str] = []
        reflection = (
            decision_context.reflection_signals
            if decision_context
            else None
        )
        if (
            reflection
            and sub_question.id
            in reflection.persistently_weak_subquestions
        ):
            queries.append(
                f"{sub_question.question} targeted recovery for "
                "persistent cross-round weakness"
            )
        if reflection and reflection.repeatedly_ineffective_sources:
            excluded = " ".join(
                reflection.repeatedly_ineffective_sources
            )
            queries.append(
                f"{sub_question.question} alternative primary sources "
                f"excluding repeatedly ineffective domains {excluded}"
            )
        if reflection and reflection.repeated_critic_issue_types:
            repeated_types = " ".join(
                item[0] for item in reflection.repeated_critic_issue_types
            )
            queries.append(
                f"{sub_question.question} resolve repeated critic patterns "
                f"{repeated_types}"
            )
        if (
            reflection
            and reflection.ineffective_replanning_iterations
        ):
            rounds = " ".join(
                str(item)
                for item in reflection.ineffective_replanning_iterations
            )
            queries.append(
                f"{sub_question.question} new evidence angle after "
                f"no-progress replanning rounds {rounds}"
            )
        targeted_issues = (
            [
                issue
                for issue in decision_context.unresolved_critic_issues
                if sub_question.id in issue.sub_question_ids
            ]
            if decision_context
            else []
        )
        for issue in targeted_issues:
            queries.append(
                f"{sub_question.question} resolve {issue.issue_type}: "
                f"{issue.message}"
            )
        if "independent_source_domains" in metrics.gaps:
            queries.append(
                f"{sub_question.question} independent alternative source"
            )
        if "counterargument" in metrics.gaps:
            queries.append(
                f"{sub_question.question} risk constraint counterargument"
            )
        if "freshness" in metrics.gaps:
            queries.append(
                f"{sub_question.question} latest update as of {as_of.isoformat()}"
            )
        if "evidence_count" in metrics.gaps:
            queries.append(
                f"{sub_question.question} official evidence verification"
            )
        if "average_confidence" in metrics.gaps:
            queries.append(
                f"{sub_question.question} primary source confirmation"
            )
        if "unresolved_critic_issues" in metrics.gaps:
            queries.append(
                f"{sub_question.question} resolve critic evidence gap"
            )
        if not queries:
            queries.append(
                f"{sub_question.question} unexplored evidence angle"
            )
        sub_question.search_queries = list(dict.fromkeys(queries))[:3]
        refined[sub_question.id] = list(sub_question.search_queries)

    inputs: dict[str, object] = {
        "iteration": iteration,
        "sufficiency_score": sufficiency.score,
        "gaps_by_sub_question": gaps_by_id,
        "as_of": as_of.isoformat(),
    }
    if decision_context:
        fields = [
            "iteration",
            "sufficiency",
            "unresolved_critic_issues",
        ]
        if decision_context.reflection_signals.present:
            fields.append("reflection_signals")
        inputs["decision_context_fields"] = fields
        inputs["decision_context"] = decision_context.field_snapshot(
            *fields
        )
    record_agent_decision(
        state,
        AgentDecision(
            decision_type="research_replan",
            made_by="PlannerAgent",
            inputs=inputs,
            criterion=(
                "replace the next-round search intent with deterministic "
                "queries targeted at measured sufficiency gaps"
                + (
                    " and unresolved DecisionContext critic issues"
                    if decision_context
                    else ""
                )
                + (
                    " and deterministic cross-round reflection signals"
                    if decision_context
                    and decision_context.reflection_signals.present
                    else ""
                )
            ),
            outcome=f"refined_queries={refined}",
            alternatives_considered=[
                "repeat_previous_queries",
                "stop_with_current_coverage",
                "refine_queries_from_gaps",
            ],
            iteration=iteration,
        ),
    )
    return refined


def _issue_counts(state: ResearchState) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not state.plan or not state.critic_report:
        return counts
    evidence_subq = {item.id: item.sub_question_id for item in state.evidence_store}
    all_ids = [item.id for item in state.plan.sub_questions]
    for issue in state.critic_report.issues:
        targets: set[str] = set()
        if issue.suggested_retry_task and issue.suggested_retry_task.sub_question_id:
            targets.add(issue.suggested_retry_task.sub_question_id)
        targets.update(
            evidence_subq[item]
            for item in issue.affected_claims
            if item in evidence_subq
        )
        if not targets:
            targets.update(all_ids)
        for target in targets:
            counts[target] = counts.get(target, 0) + 1
    return counts


def _has_counterargument(evidence: list[Evidence]) -> bool:
    joined = " ".join(item.claim.lower() for item in evidence)
    return any(term in joined for term in COUNTERARGUMENT_TERMS)


def _source_domain(evidence: Evidence) -> str:
    parts = urlsplit(evidence.source_url)
    return parts.netloc.lower() or parts.scheme.lower()


def _ratio(value: float, threshold: float) -> float:
    if threshold <= 0:
        return 1.0
    return min(1.0, value / threshold)
