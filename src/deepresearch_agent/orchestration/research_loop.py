from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from pydantic import Field

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.counterargument_policy import (
    counterargument_required,
)
from deepresearch_agent.metric_coverage import (
    MetricCoverageItem,
    canonical_metric,
    evaluate_metric_coverage,
)
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    ResearchState,
    StrictModel,
    SubQuestion,
)

if TYPE_CHECKING:
    from deepresearch_agent.orchestration.decision_context import (
        DecisionContext,
    )


class ReplanDomainPolicy(Protocol):
    """Domain-owned query directions required by deterministic replanning."""

    def document_type_for_direction(self, direction: str) -> str: ...

    def metric_gap_direction(self) -> str: ...

    def evidence_gap_direction(self) -> str: ...

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
# The 019-B hand-written probe set has a 15--42 Chinese-character range.  Forty
# eight leaves room for an issuer name, ticker, metric, period and document type
# while making a pasted sub-question visibly impossible.
MAX_REPLAN_QUERY_CHARS = 48
MAX_REPLAN_QUERY_CHINESE_CHARS = 48
MAX_TITLE_COMMON_SUBSTRING_CHARS = 12
_INTERNAL_QUERY_TERMS = re.compile(
    r"resolve\s+|unverified_[a-z_]+|[a-z]+_gap|confidence:|"
    r"Projection claim|critic|issue_id|"
    r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b",
    re.IGNORECASE,
)
_QUESTION_STYLE_TERMS = re.compile(
    r"有哪些|是什么|为什么|为何|如何|是否|可核验事实|"
    r"研究|分析|解读|梳理|综述|请",
)
_ISSUE_DIRECTIONS = {
    "missing_citation": "官方来源 原始公告 核验",
    "numeric_conflict": "官方数据 统计口径 单位 核验",
    "temporal_conflict": "官方披露 时间线 日期 核验",
    "outdated_source": "最新官方披露 更新",
    "missing_counterargument": "风险 限制 反方证据",
    "unverified_projection": "官方披露 建设进展 实际日期",
    "injection_risk": "独立官方来源 交叉验证",
    "contradicts_prior": "前后期官方披露 口径对比",
    "numeric_inconsistency": "官方数据 计算口径 单位 核验",
}
def build_replan_query(
    question: str | SubQuestion,
    document_type: str,
) -> str:
    """Build entity/facet/document queries without question-style prose."""

    sub_question = question if isinstance(question, SubQuestion) else None
    question_text = sub_question.question if sub_question else str(question)
    identifiers: list[str] = []
    metrics: list[str] = []
    periods: list[str] = []
    if sub_question:
        for request in sub_question.structured_data_requests:
            if request.company_name:
                identifiers.append(
                    request.company_name
                    if request.symbol
                    else f"{request.company_name} 公司"
                )
            if request.symbol:
                identifiers.append(request.symbol)
            metrics.extend(request.metrics)
            periods.extend(request.periods)
    if not sub_question:
        raise ValueError("Structured SubQuestion is required for a replan query")
    # Non-financial legacy plans have no structured request.  Do not fall back
    # to their prose title: retain a neutral structured entity placeholder so
    # the query remains a field assembly and is visibly low-specificity.
    if not identifiers:
        identifiers.append("研究主体")
    # The domain boundary supplies the target document type; no title
    # words, critic prose, or question text is allowed to enter the query.
    if not document_type.strip():
        raise ValueError("Replan query requires a target document type")
    metric_field = list(dict.fromkeys(metrics)) or ["事项"]
    period_field = list(dict.fromkeys(periods))
    query = " ".join(
        dict.fromkeys(
            [
                *identifiers,
                *metric_field,
                *period_field,
                document_type,
            ]
        )
    )
    query = _INTERNAL_QUERY_TERMS.sub(" ", query)
    query = " ".join(query.split())
    query = query[:MAX_REPLAN_QUERY_CHARS].rstrip()
    _validate_replan_query(query, question_text)
    return query


def longest_common_substring_length(left: str, right: str) -> int:
    """Return the longest contiguous shared string; intentionally deterministic."""
    previous = [0] * (len(right) + 1)
    longest = 0
    for left_char in left:
        current = [0]
        for index, right_char in enumerate(right, start=1):
            value = previous[index - 1] + 1 if left_char == right_char else 0
            current.append(value)
            longest = max(longest, value)
        previous = current
    return longest


def _validate_replan_query(query: str, title: str) -> None:
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", query))
    if chinese_count > MAX_REPLAN_QUERY_CHINESE_CHARS:
        raise ValueError("Replan query exceeds Chinese-character limit")
    if longest_common_substring_length(query, title) > MAX_TITLE_COMMON_SUBSTRING_CHARS:
        raise ValueError("Replan query copies too much sub-question title text")


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
    requested_metric_count: int = Field(default=0, ge=0)
    covered_metric_count: int = Field(default=0, ge=0)
    missing_metrics: list[str] = Field(default_factory=list)
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
    coverage_by_subquestion: dict[str, list[MetricCoverageItem]] = {}
    for item in evaluate_metric_coverage(state):
        coverage_by_subquestion.setdefault(
            item.sub_question_id,
            [],
        ).append(item)
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
        dated_evidence = [item for item in evidence if item.source_pub_date]
        freshest_age = (
            min(max(0, (as_of - item.source_pub_date).days) for item in dated_evidence)
            if dated_evidence
            else None
        )
        requires_counterargument = (
            thresholds.require_counterargument
            and counterargument_required(state)
        )
        missing_counterargument = (
            requires_counterargument
            and not _has_counterargument(evidence)
        )
        unresolved = issue_counts.get(sub_question.id, 0)
        requested_coverage = coverage_by_subquestion.get(
            sub_question.id,
            [],
        )
        covered_metric_count = sum(
            1 for item in requested_coverage
            if item.status == "cited"
        )
        missing_metrics = [
            item.metric
            for item in requested_coverage
            if item.status != "cited"
        ]
        gaps: list[str] = []
        if evidence_count < thresholds.min_evidence_count:
            gaps.append("evidence_count")
        if len(domains) < thresholds.min_independent_domains:
            gaps.append("independent_source_domains")
        if average_confidence < thresholds.min_average_confidence:
            gaps.append("average_confidence")
        # Unknown is an explicit neutral freshness value: it is visible in
        # reports but does not create a permanent synthetic freshness gap.
        if freshest_age is not None and freshest_age > thresholds.max_freshness_age_days:
            gaps.append("freshness")
        if unresolved > thresholds.max_unresolved_critic_issues:
            gaps.append("unresolved_critic_issues")
        if missing_counterargument:
            gaps.append("counterargument")
        if missing_metrics:
            gaps.append("requested_metric_coverage")
        metrics.append(
            SubquestionSufficiency(
                sub_question_id=sub_question.id,
                evidence_count=evidence_count,
                independent_source_domains=len(domains),
                average_confidence=round(average_confidence, 6),
                freshest_evidence_age_days=freshest_age,
                unresolved_critic_issues=unresolved,
                missing_counterargument=missing_counterargument,
                requested_metric_count=len(requested_coverage),
                covered_metric_count=covered_metric_count,
                missing_metrics=missing_metrics,
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
                    if not missing_counterargument
                    else 0.0
                ),
            ]
        )
        if requested_coverage:
            component_scores.append(
                _ratio(
                    covered_metric_count,
                    len(requested_coverage),
                )
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
    domain_pack: ReplanDomainPolicy,
) -> dict[str, list[str]]:
    if not state.plan:
        raise ValueError("Research re-planning requires an existing plan")
    metrics_by_id = {
        item.sub_question_id: item
        for item in sufficiency.by_sub_question
    }
    refined: dict[str, list[str]] = {}
    def query(sub_question: SubQuestion, direction: str) -> str:
        return build_replan_query(
            sub_question,
            domain_pack.document_type_for_direction(direction),
        )

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
                query(sub_question, "官方来源 补充核验")
            )
        if reflection and reflection.repeatedly_ineffective_sources:
            queries.append(
                query(sub_question, "其他一手来源 交叉验证")
            )
        if reflection and reflection.repeated_critic_issue_types:
            queries.append(
                query(sub_question, "官方来源 定向补充证据")
            )
        if (
            reflection
            and reflection.ineffective_replanning_iterations
        ):
            queries.append(
                query(sub_question, "不同一手来源 新证据角度")
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
                query(
                    sub_question,
                    _ISSUE_DIRECTIONS.get(
                        issue.issue_type,
                        "官方来源 补充核验",
                    ),
                )
            )
        if "requested_metric_coverage" in metrics.gaps:
            targeted = sub_question.model_copy(deep=True)
            missing = {
                canonical_metric(item)
                for item in metrics.missing_metrics
            }
            for request in targeted.structured_data_requests:
                request.metrics = [
                    item
                    for item in request.metrics
                    if canonical_metric(item) in missing
                ]
            queries.append(
                query(targeted, domain_pack.metric_gap_direction())
            )
        if "independent_source_domains" in metrics.gaps:
            queries.append(
                query(sub_question, "独立一手来源 交叉验证")
            )
        if "counterargument" in metrics.gaps:
            queries.append(
                query(sub_question, "风险 限制 反方证据")
            )
        if "freshness" in metrics.gaps:
            queries.append(
                query(sub_question, f"截至 {as_of.isoformat()} 最新官方披露")
            )
        if "evidence_count" in metrics.gaps:
            queries.append(
                query(sub_question, domain_pack.evidence_gap_direction())
            )
        if "average_confidence" in metrics.gaps:
            queries.append(
                query(sub_question, "一手来源 原始披露 核验")
            )
        if "unresolved_critic_issues" in metrics.gaps:
            queries.append(
                query(sub_question, "官方来源 补充核验")
            )
        if not queries:
            queries.append(
                query(sub_question, "一手来源 新证据角度")
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
