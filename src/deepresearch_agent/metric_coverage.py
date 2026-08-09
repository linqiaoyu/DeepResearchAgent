from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import Field

from deepresearch_agent.domains.protocols import MetricCoverageDomain
from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.schemas import (
    Evidence,
    ResearchState,
    StrictModel,
)

class MetricRequirement(StrictModel):
    sub_question_id: str
    metric: str
    periods: list[str] = Field(default_factory=list)


class MetricCoverageItem(StrictModel):
    sub_question_id: str
    metric: str
    requested_periods: list[str] = Field(default_factory=list)
    observed_periods: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    # Display-only provenance; coverage status never depends on this signal.
    comparison_observed: bool = False
    status: Literal["cited", "partially_cited", "searched_unavailable", "not_attempted", "unparsable_period"]
    missing_periods: list[str] = Field(default_factory=list)
    reason: str


def metric_requirements(
    state: ResearchState,
    domain_pack: MetricCoverageDomain | None = None,
) -> list[MetricRequirement]:
    """Build deterministic metric slots from the typed plan contract."""
    if not state.plan:
        return []
    pack = resolve_domain_capability(domain_pack, consumer="metric_requirements")
    merged: dict[tuple[str, str], set[str]] = defaultdict(set)
    for sub_question in state.plan.sub_questions:
        for request in sub_question.structured_data_requests:
            if request.capability != "financial_indicators":
                continue
            # R105: a metric fetched only to compute another one is not itself
            # something the reader asked about, and must not be reported to them
            # as a covered or missing metric.
            if request.purpose == "component":
                continue
            normalized_periods = [
                _period_key(item, pack) for item in request.periods
            ]
            periods = set(normalized_periods)
            # StructuredDataRequest rejects this at planning time.  Retaining
            # this branch makes legacy/replayed states fail closed too.
            unparsable = [
                raw
                for raw, normalized in zip(
                    request.periods,
                    normalized_periods,
                    strict=False,
                )
                if normalized is None
            ]
            for metric in request.metrics:
                canonical = pack.canonical_metric(metric)
                if canonical:
                    merged[(sub_question.id, canonical)].update(
                        period for period in periods if period is not None
                    )
                    for raw in unparsable:
                        merged[(sub_question.id, canonical)].add(
                            f"unparsable:{raw}"
                        )
    return [
        MetricRequirement(
            sub_question_id=sub_question_id,
            metric=metric,
            periods=sorted(periods),
        )
        for (sub_question_id, metric), periods in sorted(merged.items())
    ]


def evaluate_metric_coverage(
    state: ResearchState,
    domain_pack: MetricCoverageDomain | None = None,
) -> list[MetricCoverageItem]:
    """Resolve every requested metric to cited evidence or an explicit gap."""
    evidence_by_subquestion: dict[str, list[Evidence]] = defaultdict(list)
    for evidence in state.evidence_store:
        evidence_by_subquestion[evidence.sub_question_id].append(evidence)

    pack = resolve_domain_capability(
        domain_pack, consumer="evaluate_metric_coverage"
    )
    coverage: list[MetricCoverageItem] = []
    for requirement in metric_requirements(state, pack):
        matches = [
            item
            for item in evidence_by_subquestion.get(
                requirement.sub_question_id,
                [],
            )
            if pack.evidence_matches_metric(item, requirement.metric)
        ]
        observed_periods = sorted({
            period
            for item in matches
            for period in _evidence_periods(item, pack)
        })
        unparsable_periods = sorted(
            period.removeprefix("unparsable:")
            for period in requirement.periods
            if period.startswith("unparsable:")
        )
        requested_periods = [
            period for period in requirement.periods
            if not period.startswith("unparsable:")
        ]
        missing_periods = sorted(
            set(requested_periods) - set(observed_periods)
        )
        evidence_ids = [item.id for item in matches]
        comparison_observed = any(pack.comparison_observed(item) for item in matches)
        complete = bool(evidence_ids) and not missing_periods
        attempted = requirement.sub_question_id in state.completed_tasks
        if unparsable_periods:
            status = "unparsable_period"
            missing_periods = unparsable_periods + missing_periods
            reason = "requested periods could not be parsed=" + str(unparsable_periods)
        elif complete:
            status = "cited"
            reason = "the requested metric has at least one evidence id"
        elif evidence_ids:
            status = "partially_cited"
            reason = "the requested metric has cited evidence but lacks requested periods=" + str(missing_periods)
        elif attempted:
            status = "searched_unavailable"
            reason = (
                "research branch completed without cited coverage for "
                + (
                    f"periods={missing_periods}"
                    if missing_periods
                    else "the requested metric"
                )
            )
        else:
            status = "not_attempted"
            reason = "research branch did not complete before termination"
        coverage.append(
            MetricCoverageItem(
                sub_question_id=requirement.sub_question_id,
                metric=requirement.metric,
                requested_periods=requested_periods + unparsable_periods,
                observed_periods=observed_periods,
                evidence_ids=evidence_ids,
                comparison_observed=comparison_observed,
                status=status,
                missing_periods=missing_periods,
                reason=reason,
            )
        )
    return coverage


def canonical_metric(value: str | None, domain_pack: MetricCoverageDomain | None = None) -> str:
    return resolve_domain_capability(
        domain_pack, consumer="canonical_metric"
    ).canonical_metric(value)


def _period_key(value: str | None, domain_pack: MetricCoverageDomain) -> str | None:
    return domain_pack.parse_period(value)


def _evidence_periods(evidence: Evidence, domain_pack: MetricCoverageDomain) -> set[str]:
    # Prose can mention arbitrary comparison years; only typed values prove
    # that a requested period is covered.
    periods: set[str] = set()
    if evidence.structured_record:
        period = _period_key(evidence.structured_record.period, domain_pack)
        if period is not None:
            periods.add(period)
    if evidence.numeric_fields:
        period = _period_key(evidence.numeric_fields.period, domain_pack)
        if period is not None:
            periods.add(period)
    return periods
