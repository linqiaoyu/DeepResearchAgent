from __future__ import annotations

# Finance-domain numeric consistency rules.

import itertools
import math
import re
from dataclasses import dataclass

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    Issue,
    ResearchState,
    RetryTask,
)

_GROWTH_RE = re.compile(r"^(?P<metric>.+?)(?P<kind>同比|环比)(?:增长率|增速)$")
_CURRENCY_FACTORS = {
    "元": 1.0,
    "万元": 10_000.0,
    "万": 10_000.0,
    "百万元": 1_000_000.0,
    "亿元": 100_000_000.0,
    "亿": 100_000_000.0,
}
_PERCENT_FACTORS = {
    "%": 1.0,
    "percent": 1.0,
    "小数": 100.0,
    "decimal": 100.0,
}


@dataclass(frozen=True)
class NumericObservation:
    evidence: Evidence
    entity: str
    metric: str
    normalized_metric: str
    period: str
    scope: str
    value: float
    unit: str


class NumericConsistencyChecker:
    """Deterministic arithmetic checks over normalized Evidence fields."""

    def __init__(
        self,
        metric_table: dict[str, dict[str, str]],
        *,
        relative_tolerance: float = 0.01,
        absolute_tolerance: float = 0.01,
    ) -> None:
        if relative_tolerance < 0 or absolute_tolerance < 0:
            raise ValueError("numeric tolerances must be non-negative")
        self.aliases = metric_table.get("metric_aliases", {})
        self.dimension_aliases = metric_table.get(
            "dimension_aliases",
            {},
        )
        self.relative_tolerance = relative_tolerance
        self.absolute_tolerance = absolute_tolerance

    def check(self, state: ResearchState) -> list[Issue]:
        decisions_before = len(state.agent_decisions)
        observations = [
            item
            for evidence in state.evidence_store
            for item in [self._observation(evidence)]
            if item is not None
        ]
        issues: list[Issue] = []
        for observation in observations:
            if _GROWTH_RE.match(observation.metric):
                issues.extend(
                    self._check_growth(state, observation, observations)
                )
            if "占" in observation.metric:
                issues.extend(
                    self._check_share(state, observation, observations)
                )
            if "=" in observation.metric and "+" in observation.metric:
                issues.extend(
                    self._check_sum(state, observation, observations)
                )
        issues.extend(self._check_unit_conversions(state, observations))
        check_count = len(state.agent_decisions) - decisions_before
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="numeric_consistency_scan",
                made_by="CriticAgent",
                inputs={
                    "numeric_observation_count": len(observations),
                    "check_count": check_count,
                    "issue_count": len(issues),
                    "relative_tolerance": self.relative_tolerance,
                    "absolute_tolerance": self.absolute_tolerance,
                },
                criterion=(
                    "run every applicable deterministic growth, share, sum, "
                    "and unit-conversion relationship"
                ),
                outcome=(
                    f"checks={check_count}, issues={len(issues)}"
                ),
                alternatives_considered=[
                    "run_applicable_checks",
                    "no_applicable_relationships",
                ],
            ),
        )
        return issues

    def _check_growth(
        self,
        state: ResearchState,
        claim: NumericObservation,
        observations: list[NumericObservation],
    ) -> list[Issue]:
        match = _GROWTH_RE.match(claim.metric)
        if not match:
            return []
        base = self._normalize_metric(match.group("metric"))
        previous_period = _previous_period(
            claim.period,
            match.group("kind"),
        )
        current = self._find(
            observations,
            claim,
            normalized_metric=base,
            period=claim.period,
        )
        previous = self._find(
            observations,
            claim,
            normalized_metric=base,
            period=previous_period,
        )
        if current is None or previous is None:
            return self._scope_skip_if_applicable(
                state,
                claim,
                observations,
                metrics=(base, base),
                periods=(claim.period, previous_period),
                relationship="growth_rate",
            )
        current_value = self._common_value(current)
        previous_value = self._common_value(previous)
        if current_value is None or previous_value is None or previous_value == 0:
            return []
        calculated = (
            (current_value - previous_value) / abs(previous_value) * 100
        )
        formula = (
            f"({current_value}-{previous_value})/"
            f"abs({previous_value})*100"
        )
        return self._finish(
            state,
            relationship="growth_rate",
            claim=claim,
            calculated=calculated,
            formula=formula,
            participants=(claim, current, previous),
        )

    def _check_share(
        self,
        state: ResearchState,
        claim: NumericObservation,
        observations: list[NumericObservation],
    ) -> list[Issue]:
        relation = re.sub(r"(?:比重|比例|占比)$", "", claim.metric)
        numerator_name, separator, denominator_name = relation.partition(
            "占"
        )
        if not separator or not numerator_name or not denominator_name:
            return []
        numerator_metric = self._normalize_metric(numerator_name)
        denominator_metric = self._normalize_metric(denominator_name)
        numerator = self._find(
            observations,
            claim,
            normalized_metric=numerator_metric,
            period=claim.period,
        )
        denominator = self._find(
            observations,
            claim,
            normalized_metric=denominator_metric,
            period=claim.period,
        )
        if numerator is None or denominator is None:
            return self._scope_skip_if_applicable(
                state,
                claim,
                observations,
                metrics=(numerator_metric, denominator_metric),
                periods=(claim.period, claim.period),
                relationship="share",
            )
        if denominator.value == 0:
            return []
        numerator_value = self._common_value(numerator)
        denominator_value = self._common_value(denominator)
        if numerator_value is None or denominator_value is None:
            return []
        calculated = numerator_value / denominator_value * 100
        formula = (
            f"{numerator_value}/{denominator_value}*100"
        )
        return self._finish(
            state,
            relationship="share",
            claim=claim,
            calculated=calculated,
            formula=formula,
            participants=(claim, numerator, denominator),
        )

    def _check_sum(
        self,
        state: ResearchState,
        claim: NumericObservation,
        observations: list[NumericObservation],
    ) -> list[Issue]:
        left, right = (part.strip() for part in claim.metric.split("=", 1))
        if "+" in right and "+" not in left:
            total_name, component_text = left, right
        elif "+" in left and "+" not in right:
            total_name, component_text = right, left
        else:
            return []
        component_metrics = tuple(
            self._normalize_metric(item.strip())
            for item in component_text.split("+")
            if item.strip()
        )
        if len(component_metrics) < 2:
            return []
        components = tuple(
            self._find(
                observations,
                claim,
                normalized_metric=metric,
                period=claim.period,
            )
            for metric in component_metrics
        )
        if any(item is None for item in components):
            return self._scope_skip_if_applicable(
                state,
                claim,
                observations,
                metrics=component_metrics,
                periods=tuple(
                    claim.period for _item in component_metrics
                ),
                relationship="sum",
            )
        typed_components = tuple(
            item for item in components if item is not None
        )
        values = [
            self._convert_to_unit(item, claim.unit)
            for item in typed_components
        ]
        if any(value is None for value in values):
            return []
        calculated = sum(value for value in values if value is not None)
        formula = "+".join(str(value) for value in values)
        total_metric = self._normalize_metric(total_name)
        return self._finish(
            state,
            relationship=f"sum:{total_metric}",
            claim=claim,
            calculated=calculated,
            formula=formula,
            participants=(claim, *typed_components),
        )

    def _check_unit_conversions(
        self,
        state: ResearchState,
        observations: list[NumericObservation],
    ) -> list[Issue]:
        issues: list[Issue] = []
        groups: dict[
            tuple[str, str, str, str],
            list[NumericObservation],
        ] = {}
        for item in observations:
            if (
                item.unit not in _CURRENCY_FACTORS
                and item.unit.lower() not in _PERCENT_FACTORS
            ):
                continue
            groups.setdefault(
                (
                    item.entity,
                    item.normalized_metric,
                    item.period,
                    item.scope,
                ),
                [],
            ).append(item)
        for group in groups.values():
            for left, right in itertools.combinations(group, 2):
                if left.unit == right.unit:
                    continue
                calculated = self._convert_to_unit(right, left.unit)
                if calculated is None:
                    continue
                issues.extend(
                    self._finish(
                        state,
                        relationship="unit_conversion",
                        claim=left,
                        calculated=calculated,
                formula=(
                            f"{right.value}*"
                            f"{self._unit_factor(right.unit)}/"
                            f"{self._unit_factor(left.unit)}"
                        ),
                        participants=(left, right),
                    )
                )
        return issues

    def _finish(
        self,
        state: ResearchState,
        *,
        relationship: str,
        claim: NumericObservation,
        calculated: float,
        formula: str,
        participants: tuple[NumericObservation, ...],
    ) -> list[Issue]:
        claimed = self._percentage_value(claim)
        evidence_ids = list(
            dict.fromkeys(item.evidence.id for item in participants)
        )
        consistent = math.isclose(
            claimed,
            calculated,
            rel_tol=self.relative_tolerance,
            abs_tol=self.absolute_tolerance,
        )
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="numeric_consistency_check",
                made_by="CriticAgent",
                inputs={
                    "relationship": relationship,
                    "normalized_metric": claim.normalized_metric,
                    "scope": claim.scope,
                    "claimed_value": claimed,
                    "calculated_value": round(calculated, 8),
                    "formula": formula,
                    "evidence_ids": evidence_ids,
                    "relative_tolerance": self.relative_tolerance,
                    "absolute_tolerance": self.absolute_tolerance,
                },
                criterion=(
                    "compare normalized, scope-consistent arithmetic using "
                    "configured relative and absolute tolerances"
                ),
                outcome="pass" if consistent else "numeric_inconsistency",
                alternatives_considered=[
                    "pass",
                    "numeric_inconsistency",
                    "skip_scope_conflict",
                ],
            ),
        )
        if consistent:
            return []
        task = RetryTask(
            reason=f"Numeric relationship failed: {relationship}",
            query=(
                f"{claim.entity} {claim.metric} {claim.period} "
                "official arithmetic verification"
            ),
            source_type="official",
            sub_question_id=claim.evidence.sub_question_id,
            severity="high",
        )
        return [
            Issue(
                issue_type="numeric_inconsistency",
                severity="high",
                affected_claims=evidence_ids,
                message=(
                    f"Numeric inconsistency for {relationship}: "
                    f"claimed={claimed}, calculated={round(calculated, 8)}."
                ),
                suggested_retry_task=task,
                claimed_value=claimed,
                calculated_value=round(calculated, 8),
                formula=formula,
                evidence_ids=evidence_ids,
            )
        ]

    def _scope_skip_if_applicable(
        self,
        state: ResearchState,
        claim: NumericObservation,
        observations: list[NumericObservation],
        *,
        metrics: tuple[str, ...],
        periods: tuple[str, ...],
        relationship: str,
    ) -> list[Issue]:
        loose = [
            item
            for metric, period in zip(metrics, periods, strict=True)
            for item in [
                self._find(
                    observations,
                    claim,
                    normalized_metric=metric,
                    period=period,
                    require_same_scope=False,
                )
            ]
            if item is not None
        ]
        if len(loose) != len(metrics) or all(
            item.scope == claim.scope for item in loose
        ):
            return []
        evidence_ids = list(
            dict.fromkeys([claim.evidence.id, *(item.evidence.id for item in loose)])
        )
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="numeric_consistency_check",
                made_by="CriticAgent",
                inputs={
                    "relationship": relationship,
                    "normalized_metric": list(metrics),
                    "scope": claim.scope,
                    "participant_scopes": [
                        item.scope for item in loose
                    ],
                    "evidence_ids": evidence_ids,
                },
                criterion=(
                    "arithmetic verification requires normalized metrics and "
                    "the same scope"
                ),
                outcome="skip_scope_conflict",
                alternatives_considered=[
                    "verify",
                    "numeric_inconsistency",
                    "skip_scope_conflict",
                ],
            ),
        )
        return [
            Issue(
                issue_type="numeric_conflict",
                severity="medium",
                affected_claims=evidence_ids,
                message=(
                    "Scope conflict: arithmetic relationship was not checked "
                    f"because scopes differ ({claim.scope} vs "
                    f"{sorted({item.scope for item in loose})})."
                ),
            )
        ]

    def _find(
        self,
        observations: list[NumericObservation],
        anchor: NumericObservation,
        *,
        normalized_metric: str,
        period: str,
        require_same_scope: bool = True,
    ) -> NumericObservation | None:
        return next(
            (
                item
                for item in observations
                if item.evidence.id != anchor.evidence.id
                and item.entity == anchor.entity
                and item.normalized_metric == normalized_metric
                and item.period == period
                and (
                    not require_same_scope
                    or item.scope == anchor.scope
                )
            ),
            None,
        )

    def _observation(
        self,
        evidence: Evidence,
    ) -> NumericObservation | None:
        fields = evidence.numeric_fields
        if (
            evidence.claim_type != "data"
            or not fields
            or not fields.entity
            or not fields.metric_name
            or not fields.period
            or fields.value is None
        ):
            return None
        metric = fields.metric_name.strip()
        return NumericObservation(
            evidence=evidence,
            entity=re.sub(r"\s+", "", fields.entity.strip().lower()),
            metric=metric,
            normalized_metric=self._normalize_metric(metric),
            period=fields.period.strip(),
            scope=self.dimension_aliases.get(
                (fields.dimension or "未标注").strip(),
                (fields.dimension or "未标注").strip(),
            ),
            value=float(fields.value),
            unit=(fields.unit or "").strip(),
        )

    def _normalize_metric(self, metric: str) -> str:
        stripped = metric.strip()
        return self.aliases.get(stripped, stripped)

    def _percentage_value(self, item: NumericObservation) -> float:
        if item.unit.lower() in {"小数", "decimal"}:
            return item.value * 100
        return item.value

    def _common_value(self, item: NumericObservation) -> float | None:
        if item.unit in _CURRENCY_FACTORS:
            return item.value * _CURRENCY_FACTORS[item.unit]
        if item.unit.lower() in _PERCENT_FACTORS:
            return None
        return item.value

    def _convert_to_unit(
        self,
        item: NumericObservation,
        target_unit: str,
    ) -> float | None:
        if item.unit == target_unit:
            return item.value
        if (
            self._unit_family(item.unit)
            != self._unit_family(target_unit)
            or self._unit_family(item.unit) is None
        ):
            return None
        return (
            item.value
            * self._unit_factor(item.unit)
            / self._unit_factor(target_unit)
        )

    def _unit_family(self, unit: str) -> str | None:
        if unit in _CURRENCY_FACTORS:
            return "currency"
        if unit.lower() in _PERCENT_FACTORS:
            return "percentage"
        return None

    def _unit_factor(self, unit: str) -> float:
        if unit in _CURRENCY_FACTORS:
            return _CURRENCY_FACTORS[unit]
        return _PERCENT_FACTORS[unit.lower()]


def _previous_period(period: str, kind: str) -> str:
    year = re.fullmatch(r"(\d{4})", period)
    if year:
        return str(int(year.group(1)) - 1)
    quarter = re.fullmatch(r"(\d{4})Q([1-4])", period, re.I)
    if quarter:
        year_value = int(quarter.group(1))
        quarter_value = int(quarter.group(2))
        if kind == "同比":
            return f"{year_value - 1}Q{quarter_value}"
        if quarter_value > 1:
            return f"{year_value}Q{quarter_value - 1}"
        return f"{year_value - 1}Q4"
    return ""
