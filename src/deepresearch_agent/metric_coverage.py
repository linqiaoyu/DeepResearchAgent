from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from pydantic import Field

from deepresearch_agent.schemas import (
    Evidence,
    ResearchState,
    StrictModel,
)

_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_COMPARISON_RE = re.compile(
    r"同比|较上年|比上年|上年同期|较去年|比去年"
)
_METRIC_ALIASES = {
    "营收": "营业收入",
    "营业收入": "营业收入",
    "归母净利润": "归母净利润",
    "归属于母公司股东的净利润": "归母净利润",
    "归属于上市公司股东的净利润": "归母净利润",
    "主营业务毛利率": "主营业务毛利率",
    # The planner resolves an unqualified 毛利率 request to the main-business
    # contract.  PDF extractors commonly preserve the table header verbatim,
    # so that exact evidence label must close the same typed requirement.
    "毛利率": "主营业务毛利率",
}


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
    comparison_observed: bool = False
    status: Literal["cited", "searched_unavailable", "not_attempted"]
    missing_periods: list[str] = Field(default_factory=list)
    reason: str


def metric_requirements(state: ResearchState) -> list[MetricRequirement]:
    """Build deterministic metric slots from the typed plan contract."""
    if not state.plan:
        return []
    merged: dict[tuple[str, str], set[str]] = defaultdict(set)
    for sub_question in state.plan.sub_questions:
        for request in sub_question.structured_data_requests:
            if request.capability != "financial_indicators":
                continue
            periods = {_period_key(item) for item in request.periods}
            periods.discard("")
            for metric in request.metrics:
                canonical = canonical_metric(metric)
                if canonical:
                    merged[(sub_question.id, canonical)].update(periods)
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
) -> list[MetricCoverageItem]:
    """Resolve every requested metric to cited evidence or an explicit gap."""
    evidence_by_subquestion: dict[str, list[Evidence]] = defaultdict(list)
    for evidence in state.evidence_store:
        evidence_by_subquestion[evidence.sub_question_id].append(evidence)

    coverage: list[MetricCoverageItem] = []
    for requirement in metric_requirements(state):
        matches = [
            item
            for item in evidence_by_subquestion.get(
                requirement.sub_question_id,
                [],
            )
            if canonical_metric(_evidence_metric(item))
            == requirement.metric
        ]
        observed_periods = sorted({
            period
            for item in matches
            for period in _evidence_periods(item)
        })
        missing_periods = sorted(
            set(requirement.periods) - set(observed_periods)
        )
        evidence_ids = [item.id for item in matches]
        comparison_observed = any(
            _COMPARISON_RE.search(
                f"{item.claim}\n{item.extract_text}"
            )
            for item in matches
        )
        latest_period = (
            max(requirement.periods)
            if requirement.periods
            else ""
        )
        complete = bool(evidence_ids) and (
            not missing_periods
            or (
                len(requirement.periods) > 1
                and latest_period in observed_periods
                and comparison_observed
            )
        )
        attempted = requirement.sub_question_id in state.completed_tasks
        if complete:
            status = "cited"
            reason = "the requested metric has at least one evidence id"
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
                requested_periods=requirement.periods,
                observed_periods=observed_periods,
                evidence_ids=evidence_ids,
                comparison_observed=comparison_observed,
                status=status,
                missing_periods=missing_periods,
                reason=reason,
            )
        )
    return coverage


def canonical_metric(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[\s：:（）()]", "", value)
    return _METRIC_ALIASES.get(normalized, normalized)


def _period_key(value: str | None) -> str:
    if not value:
        return ""
    rendered = str(value).strip()
    if re.fullmatch(r"20\d{6}", rendered):
        return rendered[:4]
    match = _YEAR_RE.search(rendered)
    return match.group(1) if match else rendered


def _evidence_metric(evidence: Evidence) -> str | None:
    if evidence.structured_record:
        return evidence.structured_record.metric_name
    if evidence.numeric_fields:
        return evidence.numeric_fields.metric_name
    return None


def _evidence_periods(evidence: Evidence) -> set[str]:
    periods = {
        match.group(1)
        for match in _YEAR_RE.finditer(
            f"{evidence.claim}\n{evidence.extract_text}"
        )
    }
    if evidence.structured_record:
        periods.add(_period_key(evidence.structured_record.period))
    if evidence.numeric_fields:
        periods.add(_period_key(evidence.numeric_fields.period))
    periods.discard("")
    return periods
