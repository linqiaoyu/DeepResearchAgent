from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepresearch_agent.reporting import GroundedFactRenderer

from deepresearch_agent.domains.finance.vocabulary import (
    AMOUNT_UNITS,
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

    def primary_source_keyword(self, *, financial_intent: bool) -> str:
        return "年度报告" if financial_intent else "公告"

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
        from deepresearch_agent.skills.finance import finance_metric_resource_path

        return finance_metric_resource_path()

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

    def deterministic_plan(self, topic: str, depth_level: int):
        from deepresearch_agent.domains.finance.planning import FinancePlanning

        return FinancePlanning().deterministic_plan(topic, depth_level)

    def propagate_plan_identity(self, plan: object, topic: str):
        from deepresearch_agent.domains.finance.planning import FinancePlanning

        return FinancePlanning().propagate_identity(plan, topic)

    def valid_structured_request(self, request: object) -> bool:
        from deepresearch_agent.domains.finance.planning import FinancePlanning

        return FinancePlanning().valid_structured_request(request)
