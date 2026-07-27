from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from pydantic import Field

from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import (
    Evidence,
    ResearchState,
    StrictModel,
)

_COMPARISON_RE = re.compile(
    r"同比|较上年|比上年|上年同期|较去年|比去年"
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
    domain_pack: DomainPack | None = None,
) -> list[MetricRequirement]:
    """Build deterministic metric slots from the typed plan contract."""
    if not state.plan:
        return []
    pack = domain_pack or load_domain_pack("finance")
    merged: dict[tuple[str, str], set[str]] = defaultdict(set)
    for sub_question in state.plan.sub_questions:
        for request in sub_question.structured_data_requests:
            if request.capability != "financial_indicators":
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
    domain_pack: DomainPack | None = None,
) -> list[MetricCoverageItem]:
    """Resolve every requested metric to cited evidence or an explicit gap."""
    evidence_by_subquestion: dict[str, list[Evidence]] = defaultdict(list)
    for evidence in state.evidence_store:
        evidence_by_subquestion[evidence.sub_question_id].append(evidence)

    pack = domain_pack or load_domain_pack("finance")
    coverage: list[MetricCoverageItem] = []
    for requirement in metric_requirements(state, pack):
        matches = [
            item
            for item in evidence_by_subquestion.get(
                requirement.sub_question_id,
                [],
            )
            if _evidence_matches_metric(item, requirement.metric, pack)
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
        comparison_observed = any(
            _COMPARISON_RE.search(
                f"{item.claim}\n{item.extract_text}"
            )
            for item in matches
        )
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


def canonical_metric(value: str | None, domain_pack: DomainPack | None = None) -> str:
    return (domain_pack or load_domain_pack("finance")).canonical_metric(value)


def _period_key(value: str | None, domain_pack: DomainPack) -> str | None:
    return domain_pack.parse_period(value)


def _evidence_metric(evidence: Evidence) -> str | None:
    if evidence.structured_record:
        return evidence.structured_record.metric_name
    if evidence.numeric_fields:
        return evidence.numeric_fields.metric_name
    return None


def _evidence_matches_metric(
    evidence: Evidence,
    required_metric: str,
    domain_pack: DomainPack,
) -> bool:
    evidence_metric = _evidence_metric(evidence)
    if domain_pack.canonical_metric(evidence_metric) != required_metric:
        return False
    if required_metric != "主营业务毛利率":
        return True
    normalized_metric = re.sub(
        r"[\s：:（）()]",
        "",
        evidence_metric or "",
    )
    if (
        evidence.structured_record
        and normalized_metric == "主营业务毛利率"
    ):
        # An explicitly typed main-business metric is already scoped at the
        # structured-provider boundary. Extractor fields remain untrusted
        # interpretations and must still pass the dimension contract.
        return True
    dimension = (
        evidence.structured_record.dimension
        if evidence.structured_record
        else evidence.numeric_fields.dimension
        if evidence.numeric_fields
        else None
    )
    return domain_pack.numeric_citation_policy().is_main_business_margin_dimension(
        dimension
    )


def _evidence_periods(evidence: Evidence, domain_pack: DomainPack) -> set[str]:
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
