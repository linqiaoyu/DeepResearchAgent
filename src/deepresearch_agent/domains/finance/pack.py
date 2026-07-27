from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepresearch_agent.reporting import GroundedFactRenderer

from deepresearch_agent.domains.finance.vocabulary import (
    AMOUNT_UNITS,
    DEFAULT_STRUCTURED_METRICS,
    FIXTURE_METRIC_ALIASES,
    MAINLAND_EQUITY_EXCHANGE,
    STRUCTURED_METRIC_ALIASES,
    canonical_metric,
    parse_period,
)


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

    def equity_exchange_label(self) -> str:
        return MAINLAND_EQUITY_EXCHANGE

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

        return FinanceGroundedFactRenderer()

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
