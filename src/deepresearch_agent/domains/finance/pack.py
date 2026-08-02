from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import re
from typing import TYPE_CHECKING

from deepresearch_agent.domains.protocols import RetrievalFilterValues
if TYPE_CHECKING:
    from deepresearch_agent.reporting import GroundedFactRenderer

from deepresearch_agent.domains.finance.vocabulary import (
    AMOUNT_UNITS,
    DEFAULT_STRUCTURED_METRICS,
    FIXTURE_METRIC_ALIASES,
    MAINLAND_EQUITY_EXCHANGE,
    STRUCTURED_METRIC_ALIASES,
    STRUCTURED_METRIC_UNITS,
    SEC_COMPANYFACTS_CONCEPTS,
    canonical_metric,
    parse_period,
)


def _issuer_aliases() -> dict[str, tuple[str, str]]:
    """Load optional public issuer aliases only when retrieval asks for them."""

    from deepresearch_agent.domains.finance.issuer_aliases import issuer_aliases

    return issuer_aliases()


class FinanceDomainPack:
    name = "finance"

    def canonical_metric(self, value: str | None) -> str:
        return canonical_metric(value)

    def parse_period(self, value: str | None) -> str | None:
        return parse_period(value)

    def amount_units(self) -> Mapping[str, Decimal]:
        return AMOUNT_UNITS

    def structured_metric_aliases(self) -> Mapping[str, str]:
        return STRUCTURED_METRIC_ALIASES

    def fixture_metric_aliases(self) -> Mapping[str, str]:
        return FIXTURE_METRIC_ALIASES

    def default_structured_metrics(self) -> tuple[str, ...]:
        return DEFAULT_STRUCTURED_METRICS

    def structured_metric_unit(self, metric_name: str) -> str | None:
        return STRUCTURED_METRIC_UNITS.get(metric_name)

    def equity_exchange_label(self) -> str:
        return MAINLAND_EQUITY_EXCHANGE

    def structured_issuer_aliases(self) -> Mapping[str, str]:
        """Map public local issuer names to the SEC registrant-name candidate."""

        return {chinese: english for chinese, (_entity_id, english) in _issuer_aliases().items()}

    def structured_xbrl_concepts(self) -> Mapping[str, tuple[str, ...]]:
        return SEC_COMPANYFACTS_CONCEPTS

    def primary_source_keyword(self, *, financial_intent: bool) -> str:
        return "年度报告" if financial_intent else "公告"

    def primary_source_terms(self, *, financial_intent: bool) -> tuple[str, ...]:
        if not financial_intent:
            return ()
        return (
            "合并资产负债表",
            "合并利润表",
            "营业收入",
            "营业成本",
            "毛利率",
            "归属于母公司股东的净利润",
            "主营业务分行业情况",
        )

    def grounded_fact_renderer(self) -> GroundedFactRenderer:
        from deepresearch_agent.domains.finance.grounded_facts import (
            FinanceGroundedFactRenderer,
        )

        return FinanceGroundedFactRenderer(self)

    def table_extractors(self):
        from deepresearch_agent.domains.finance.table_extraction import (
            FinanceTableExtractors,
        )

        return FinanceTableExtractors()

    def metric_table_path(self) -> Path:
        from deepresearch_agent.domains.finance.skills import (
            finance_metric_resource_path,
        )

        return finance_metric_resource_path()

    def metric_claim_pattern(self):
        from deepresearch_agent.domains.finance.structured_output import (
            METRIC_CLAIM_PATTERN,
        )

        return METRIC_CLAIM_PATTERN

    def comparison_observed(self, evidence: object) -> bool:
        from deepresearch_agent.domains.finance.metric_coverage import (
            comparison_observed,
        )

        return comparison_observed(evidence)

    def evidence_matches_metric(self, evidence: object, required_metric: str) -> bool:
        from deepresearch_agent.domains.finance.metric_coverage import (
            evidence_matches_metric,
        )

        return evidence_matches_metric(evidence, required_metric)

    def demo_numeric_claim(self, claims: list[object]) -> object | None:
        from deepresearch_agent.domains.finance.research_snapshot import (
            demo_numeric_claim,
        )

        return demo_numeric_claim(claims)

    def demo_scope_claim(
        self,
        claims: list[object],
        numeric_change: object | None,
    ) -> object | None:
        from deepresearch_agent.domains.finance.research_snapshot import (
            demo_scope_claim,
        )

        return demo_scope_claim(claims, numeric_change)

    def scope_change_summary(self, label: str) -> str:
        from deepresearch_agent.domains.finance.research_snapshot import (
            scope_change_summary,
        )

        return scope_change_summary(label)

    def is_full_annual_report_query(self, keyword: str) -> bool:
        from deepresearch_agent.domains.finance.disclosure_policy import (
            is_full_annual_report_query,
        )

        return is_full_annual_report_query(keyword)

    def is_full_annual_report_title(self, title: str) -> bool:
        from deepresearch_agent.domains.finance.disclosure_policy import (
            is_full_annual_report_title,
        )

        return is_full_annual_report_title(title)

    def report_year_from_title(self, title: str) -> int | None:
        from deepresearch_agent.domains.finance.disclosure_policy import (
            report_year_from_title,
        )

        return report_year_from_title(title)

    def is_amount_unit(self, value: str) -> bool:
        from deepresearch_agent.domains.finance.disclosure_policy import is_amount_unit

        return is_amount_unit(value)

    def golden_type_distribution(self) -> Mapping[str, int]:
        return {"财报解读": 8, "对比研究": 8, "行业研究": 7, "事件时间线": 7}

    def evidence_explains_change(self, text: str) -> bool:
        return any(term in text.lower() for term in ("同比", "环比", "增长", "下降", "变化", "由于"))

    def document_type_tokens(self) -> tuple[str, ...]:
        return ("年度报告", "季度报告", "公告", "年报", "季报", "统计", "发布", "报告")

    def document_type_for_direction(self, direction: str) -> str:
        explicit = next((token for token in self.document_type_tokens() if token in direction), None)
        if explicit:
            return explicit
        if any(token in direction for token in ("统计口径", "数据", "单位")):
            return "统计"
        if any(token in direction for token in ("其他", "不同", "独立")):
            return "发布"
        if any(token in direction for token in ("风险", "反方", "限制")):
            return "报告"
        if any(token in direction for token in ("原始", "证据")):
            return "年报"
        return "公告"

    def metric_gap_direction(self) -> str:
        return "年度报告 定向补齐指标"

    def evidence_gap_direction(self) -> str:
        return "官方公告 年报 补充证据"

    def metric_skill_applicable(self, metadata: object, context: str) -> bool:
        from deepresearch_agent.domains.finance.skills import (
            finance_metric_skill_applicable,
        )

        return finance_metric_skill_applicable(metadata, context)  # type: ignore[arg-type]

    def numeric_consistency_checker(
        self,
        metric_table: dict[str, object],
        *,
        relative_tolerance: float,
        absolute_tolerance: float,
    ):
        from deepresearch_agent.domains.finance.numeric_checker import (
            NumericConsistencyChecker,
        )

        return NumericConsistencyChecker(
            metric_table,
            relative_tolerance=relative_tolerance,
            absolute_tolerance=absolute_tolerance,
        )

    def numeric_citation_policy(self):
        from deepresearch_agent.domains.finance.numeric_citations import (
            FinanceNumericCitationPolicy,
        )

        return FinanceNumericCitationPolicy()

    def deterministic_plan(self, topic: str, depth_level: int):
        from deepresearch_agent.domains.finance.planning import FinancePlanning

        return FinancePlanning().deterministic_plan(topic, depth_level)

    def propagate_plan_identity(self, plan: object, topic: str):
        from deepresearch_agent.domains.finance.planning import FinancePlanning

        return FinancePlanning().propagate_identity(plan, topic)

    def valid_structured_request(self, request: object) -> bool:
        from deepresearch_agent.domains.finance.planning import FinancePlanning

        return FinancePlanning().valid_structured_request(request)

    def retrieval_filter_values(self, query: str) -> RetrievalFilterValues:
        """Emit the authority-backed issuer and fiscal-year retrieval facets."""

        entity_ids = tuple(
            entity_id
            for chinese, (entity_id, _english) in _issuer_aliases().items()
            if chinese in query
        )
        period_labels = tuple(sorted(set(re.findall(r"20\d{2}", query))))
        return RetrievalFilterValues(
            entity_ids=entity_ids,
            period_labels=period_labels,
        )

    def expand_retrieval_query(self, query: str) -> str:
        """Append a public issuer alias while preserving the original request."""

        aliases = [
            english
            for chinese, (_entity_id, english) in _issuer_aliases().items()
            if chinese in query
        ]
        return " ".join((query, *aliases))
