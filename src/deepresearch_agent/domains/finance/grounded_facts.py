from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from deepresearch_agent.domains.finance.numeric_citations import (
    has_financial_numeric_mismatch,
)
from deepresearch_agent.domains.protocols import ReportingDomain
from deepresearch_agent.metric_coverage import evaluate_metric_coverage
from deepresearch_agent.reporting.grounded_facts import (
    GroundedFactBatch,
    GroundedReaderClaim,
)
from deepresearch_agent.schemas import Evidence, ResearchState
from deepresearch_agent.structured_output import metric_fact_keys

_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_COMPARISON_RE = re.compile(
    r"同比|较上年|比上年|较去年|比去年|上升|下降|增长|减少|增加"
)
_EXACT_RMB_RE = re.compile(
    r"(?<![\d,])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*元"
)
_FINANCIAL_ATOM_RE = re.compile(
    r"-?\d[\d,]*(?:\.\d+)?\s*(?:元|万元|亿元|%|个百分点)"
)


class FinanceGroundedFactRenderer:
    """Render requested financial facts from typed Evidence and exact values."""

    def __init__(self, domain_pack: ReportingDomain | None = None) -> None:
        if domain_pack is None:
            from deepresearch_agent.domains.finance.pack import FinanceDomainPack

            domain_pack = FinanceDomainPack()
        self.domain_pack = domain_pack

    def render(self, state: ResearchState) -> GroundedFactBatch:
        evidence_by_id = {item.id: item for item in state.evidence_store}
        fact_keys_by_id = metric_fact_keys(state.evidence_store, self.domain_pack)
        rendered: list[GroundedReaderClaim] = []
        gaps: list[str] = []
        coverage_items = evaluate_metric_coverage(state, self.domain_pack)
        for coverage in coverage_items:
            if coverage.status != "cited":
                gaps.append(coverage.metric)
                continue
            candidates = [
                evidence_by_id[evidence_id]
                for evidence_id in coverage.evidence_ids
                if evidence_id in evidence_by_id
            ]
            selected = self._select_period_evidence(
                candidates,
                coverage.requested_periods,
            )
            if not selected:
                gaps.append(coverage.metric)
                continue
            parts = [self._canonical_text(item) for item in selected]
            if not any(_COMPARISON_RE.search(part) for part in parts):
                comparison = self._derived_comparison(selected)
                if comparison:
                    parts.append(comparison)
            evidence_ids = tuple(item.id for item in selected)
            rendered.append(
                GroundedReaderClaim(
                    text=f"{coverage.metric}：" + "；".join(parts) + "。",
                    evidence_ids=evidence_ids,
                    fact_keys=frozenset(
                        key
                        for evidence_id in evidence_ids
                        for key in fact_keys_by_id.get(evidence_id, set())
                    ),
                    label=coverage.metric,
                )
            )
        return GroundedFactBatch(
            required_labels=tuple(item.metric for item in coverage_items),
            claims=tuple(rendered),
            gaps=tuple(gaps),
        )

    def is_supported(
        self,
        text: str,
        evidence: list[Evidence],
        state: ResearchState,
        *,
        labels: set[str],
    ) -> bool:
        del state
        return self._exact_currency_values_supported(text, evidence) and not (
            has_financial_numeric_mismatch(
                text,
                evidence,
                required_metrics=labels,
            )
        )

    def _select_period_evidence(
        self,
        candidates: list[Evidence],
        requested_periods: list[str],
    ) -> list[Evidence]:
        selected: list[Evidence] = []
        seen: set[str] = set()
        periods = sorted(set(requested_periods), reverse=True)
        for period in periods:
            matches = [
                item
                for item in candidates
                if period in self._periods(item)
            ]
            if not matches:
                continue
            best = max(matches, key=self._evidence_rank)
            if best.id not in seen:
                selected.append(best)
                seen.add(best.id)
        if not selected:
            selected = sorted(
                candidates,
                key=self._evidence_rank,
                reverse=True,
            )[:2]
        return selected

    def _evidence_rank(self, evidence: Evidence) -> tuple[int, int, str]:
        return (
            2 if evidence.source_tier == "primary" else 1,
            1 if evidence.source_kind == "structured" else 0,
            evidence.id,
        )

    def _periods(self, evidence: Evidence) -> set[str]:
        if evidence.structured_record:
            year = self._period_year(evidence.structured_record.period)
            if year:
                return {year}
        if evidence.numeric_fields and evidence.numeric_fields.period:
            year = self._period_year(evidence.numeric_fields.period)
            if year:
                return {year}
        return {
            match.group(1)
            for match in _YEAR_RE.finditer(evidence.claim)
        }

    def _canonical_text(self, evidence: Evidence) -> str:
        record = evidence.structured_record
        if record:
            period = self._display_period(record.period)
            return (
                f"{record.entity}{period}{record.dimension}"
                f"{record.metric_name}为"
                f"{self._format_value(record.value, record.unit)}"
            )
        if (
            self._exact_currency_values_supported(
                evidence.claim,
                [evidence],
            )
            and _FINANCIAL_ATOM_RE.search(evidence.claim)
            and not has_financial_numeric_mismatch(
                evidence.claim,
                [evidence],
            )
        ):
            return evidence.claim.rstrip("。")
        fields = evidence.numeric_fields
        if fields and fields.value is not None:
            period = self._display_period(fields.period or "")
            entity = fields.entity or ""
            metric = fields.metric_name or "该指标"
            return (
                f"{entity}{period}{fields.dimension}{metric}为"
                f"{self._format_value(fields.value, fields.unit or '')}"
            )
        return "该指标的生成文本未通过保真校验，未展示数值"

    def _derived_comparison(self, evidence: list[Evidence]) -> str | None:
        values: list[tuple[str, Decimal, str]] = []
        for item in evidence:
            record = item.structured_record
            fields = item.numeric_fields
            raw_period = (
                record.period
                if record
                else fields.period
                if fields and fields.period
                else ""
            )
            year = self._period_year(raw_period)
            value = (
                record.value
                if record
                else fields.value
                if fields
                else None
            )
            unit = record.unit if record else fields.unit if fields else ""
            if year and value is not None and unit:
                values.append((year, Decimal(str(value)), unit))
        by_year = {year: (value, unit) for year, value, unit in values}
        if len(by_year) < 2:
            return None
        current_year, prior_year = sorted(by_year, reverse=True)[:2]
        current, current_unit = by_year[current_year]
        prior, prior_unit = by_year[prior_year]
        if prior == 0 or current_unit != prior_unit:
            return None
        change = ((current - prior) / abs(prior) * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        direction = "增长" if change >= 0 else "下降"
        return (
            f"由{current_year}/{prior_year}两期原值机械计算同比"
            f"{direction}{abs(change):.2f}%"
        )

    def _display_period(self, value: str) -> str:
        year = self._period_year(value)
        return f" {year}年 " if year else " "

    def _period_year(self, value: str) -> str:
        rendered = str(value).strip()
        if re.fullmatch(r"20\d{6}", rendered):
            return rendered[:4]
        match = _YEAR_RE.search(rendered)
        return match.group(1) if match else ""

    def _format_value(self, value: Decimal, unit: str) -> str:
        decimal = Decimal(str(value))
        if unit == "元":
            return f"{decimal:,f}元"
        normalized = format(decimal, "f").rstrip("0").rstrip(".")
        return f"{normalized}{unit}"

    def _exact_currency_values_supported(
        self,
        text: str,
        evidence: list[Evidence],
    ) -> bool:
        observed = {
            Decimal(match.replace(",", ""))
            for match in _EXACT_RMB_RE.findall(text)
        }
        if not observed:
            return True
        allowed: set[Decimal] = set()
        for item in evidence:
            if item.structured_record and item.structured_record.unit == "元":
                allowed.add(Decimal(str(item.structured_record.value)))
            if (
                item.numeric_fields
                and item.numeric_fields.value is not None
                and item.numeric_fields.unit == "元"
            ):
                allowed.add(Decimal(str(item.numeric_fields.value)))
            allowed.update(
                Decimal(match.replace(",", ""))
                for match in _EXACT_RMB_RE.findall(item.extract_text)
            )
        return observed <= allowed
