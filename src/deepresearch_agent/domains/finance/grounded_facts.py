from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from deepresearch_agent.domains.finance.disclosure_policy import (
    reader_metric_partial_note,
)
from deepresearch_agent.domains.finance.numeric_citations import (
    has_financial_numeric_mismatch,
)
from deepresearch_agent.domains.protocols import ReportingDomain
from deepresearch_agent.metric_coverage import (
    MetricCoverageItem,
    evaluate_metric_coverage,
)
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
# R107: `_format_value` writes `602,315,354,000 元`, but the branch that quotes
# a verified claim verbatim writes whatever the source wrote, and the R107 BYD
# run put `777,102,455,000元` in 关键发现 while 指标覆盖状态 gave the same
# figure as `777,102,455,000 元` -- one report, one number, two renderings, and
# the second is the one `check_reader_visible_contract.py` requires. The space
# is typography: only whitespace between a figure and its currency unit is
# touched, never a digit, and percentages keep the tight form readers expect.
_CURRENCY_SPACING_RE = re.compile(r"(\d)[ \t]*(亿元|万元|元)")
#: Units whose year-on-year change is a difference in points, not a ratio.
_RATE_UNITS = re.compile(r"%|个百分点")


def _normalize_currency_spacing(text: str) -> str:
    return _CURRENCY_SPACING_RE.sub(r"\1 \2", text)


def _is_renderable(coverage: MetricCoverageItem) -> bool:
    """Decide whether 关键发现 owes the reader a value for this metric.

    R109: the answer used to be `status == "cited"`, so a metric covered for
    2024 but not 2023 produced a `未取得可引用的原始披露事实` line two sections
    above a 指标覆盖状态 line reading `部分已引用；已覆盖 2024`. One state, two
    subsystems, opposite conclusions, both printed. The condition below is the
    exact statement 指标覆盖状态 makes: whenever it names a covered period, the
    findings section renders that period.
    """

    if coverage.status == "cited":
        return True
    return coverage.status == "partially_cited" and bool(coverage.observed_periods)


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
        metric_counts = Counter(item.metric for item in coverage_items)
        for coverage in coverage_items:
            label = (
                coverage.metric
                if metric_counts[coverage.metric] == 1
                else f"{coverage.sub_question_id} · {coverage.metric}"
            )
            if not _is_renderable(coverage):
                gaps.append(label)
                continue
            candidates = [
                evidence_by_id[evidence_id]
                for evidence_id in coverage.evidence_ids
                if evidence_id in evidence_by_id
            ]
            selections = self._ranked_selections(
                candidates,
                coverage.requested_periods,
            )
            if not selections:
                gaps.append(label)
                continue
            partial = coverage.status == "partially_cited"
            selected, text = self._first_supported_selection(
                selections,
                metric=coverage.metric,
                label=label,
                state=state,
                missing_periods=(
                    tuple(coverage.missing_periods) if partial else ()
                ),
            )
            evidence_ids = tuple(item.id for item in selected)
            fact_keys = frozenset(
                key
                for evidence_id in evidence_ids
                for key in fact_keys_by_id.get(evidence_id, set())
            )
            # The reporter rejects a claim carrying no fact key outright, and a
            # period can be matched by a bare year in prose that carries none.
            # A partial metric selected that way degrades to the gap it already
            # was rather than aborting the report it used to be excluded from.
            if partial and not fact_keys:
                gaps.append(label)
                continue
            rendered.append(
                GroundedReaderClaim(
                    text=text,
                    evidence_ids=evidence_ids,
                    fact_keys=fact_keys,
                    label=label,
                )
            )
        return GroundedFactBatch(
            required_labels=tuple(
                item.metric
                if metric_counts[item.metric] == 1
                else f"{item.sub_question_id} · {item.metric}"
                for item in coverage_items
            ),
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

    # R107: the highest-ranked evidence for a period is not always evidence a
    # claim can be built on. R105's A-share run ranked two annual-report PDF
    # extracts above the two AKShare records because `source_tier` outranks
    # being typed -- but each PDF extract was the bare digit string
    # `170,899,152,276.34`, which names no metric, so the fidelity guard could
    # not tell what the number measured and rejected the claim. Selecting once
    # and rendering blind meant that rejection deleted the metric: the reader
    # was told `未取得可引用的原始披露事实` for revenue while the same report's
    # coverage section quoted both years from the records that were discarded.
    # Rank the whole selection instead, and keep the first one whose rendered
    # claim the guard actually accepts. A guard rejection now redirects the
    # selection rather than costing the reader the fact.
    def _first_supported_selection(
        self,
        selections: list[list[Evidence]],
        *,
        metric: str,
        label: str,
        state: ResearchState,
        missing_periods: tuple[str, ...] = (),
    ) -> tuple[list[Evidence], str]:
        for selection in selections:
            text = self._claim_text(metric, selection, missing_periods)
            if self.is_supported(text, selection, state, labels={label}):
                return selection, text
        # Nothing survives the guard. Return the top-ranked selection unchanged
        # so the reporter reaches the same rejection it would have reached
        # before, and the metric degrades to a gap rather than to an unchecked
        # claim.
        return selections[0], self._claim_text(
            metric,
            selections[0],
            missing_periods,
        )

    def _claim_text(
        self,
        metric: str,
        selected: list[Evidence],
        missing_periods: tuple[str, ...] = (),
    ) -> str:
        parts = [
            _normalize_currency_spacing(self._canonical_text(item))
            for item in selected
        ]
        if not any(_COMPARISON_RE.search(part) for part in parts):
            comparison = self._derived_comparison(selected)
            if comparison:
                parts.append(comparison)
        # A bare period carries no measure unit, so naming the uncovered one
        # adds no value the fidelity guard has to support.
        note = reader_metric_partial_note(missing_periods)
        if note:
            parts.append(note)
        return f"{metric}：" + "；".join(parts) + "。"

    def _ranked_selections(
        self,
        candidates: list[Evidence],
        requested_periods: list[str],
    ) -> list[list[Evidence]]:
        """Return per-period evidence picks, best first, then each next best."""
        periods = sorted(set(requested_periods), reverse=True)
        ranked_by_period: list[list[Evidence]] = []
        for period in periods:
            matches = sorted(
                (item for item in candidates if period in self._periods(item)),
                key=self._evidence_rank,
                reverse=True,
            )
            if matches:
                ranked_by_period.append(matches)
        if not ranked_by_period:
            fallback = sorted(
                candidates,
                key=self._evidence_rank,
                reverse=True,
            )[:2]
            return [fallback] if fallback else []
        selections: list[list[Evidence]] = []
        seen: set[tuple[str, ...]] = set()
        for index in range(max(len(matches) for matches in ranked_by_period)):
            selection: list[Evidence] = []
            chosen: set[str] = set()
            for matches in ranked_by_period:
                # A period with fewer alternatives keeps its last one rather
                # than dropping out, so a deeper retry never silently reports
                # fewer periods than the question asked for.
                item = matches[min(index, len(matches) - 1)]
                if item.id not in chosen:
                    selection.append(item)
                    chosen.add(item.id)
            key = tuple(item.id for item in selection)
            if selection and key not in seen:
                seen.add(key)
                selections.append(selection)
        return selections

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
        # R108: a margin that moves from 20.21% to 19.44% has fallen 0.78
        # percentage points, not 3.84%. This divided every metric by its prior
        # period regardless of unit, so the first run that delivered a rate
        # stated the relative change in a form readers read as points. It also
        # put a figure past the fidelity guard unchecked, because
        # `_derived_yoy_values` derives a rate's year-on-year as the difference
        # -- the two sides were computing different quantities and only the
        # unextractable phrasing kept them from disagreeing out loud.
        if _RATE_UNITS.fullmatch(current_unit):
            points = (current - prior).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            direction = "上升" if points >= 0 else "下降"
            return (
                f"由{current_year}/{prior_year}两期原值机械计算同比"
                f"{direction}{abs(points):.2f}个百分点"
            )
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
        normalized = format(decimal, ",f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        if unit == "%":
            # R108: `19.43834 %` is not how a rate is written. Currency units
            # keep their space (R107); a percent sign does not take one.
            return f"{normalized}%"
        return f"{normalized} {unit}" if unit else normalized

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
