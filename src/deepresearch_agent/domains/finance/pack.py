from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from deepresearch_agent.domains.finance.vocabulary import (
    AMOUNT_UNITS,
    canonical_metric,
    parse_period,
)


class FinanceDomainPack:
    name = "finance"

    def canonical_metric(self, value: str | None) -> str:
        return canonical_metric(value)

    def parse_period(self, value: str | None) -> str:
        return parse_period(value)

    def amount_units(self) -> Mapping[str, Decimal]:
        return AMOUNT_UNITS

    def primary_source_keyword(self, *, financial_intent: bool) -> str:
        return "年度报告" if financial_intent else "公告"
