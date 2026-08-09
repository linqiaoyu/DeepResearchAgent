"""Finance-owned deterministic derived metrics for reader reports."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

_REVENUE_NAMES = {"营业收入", "revenue"}
_GROSS_PROFIT_NAMES = {"毛利", "grossprofit", "gross profit"}


def reader_derived_metrics(evidence: list[Any]) -> list[dict[str, Any]]:
    """Gross margin for every period whose revenue and gross profit are both in hand.

    R102: this returned at most one value and ignored the period entirely,
    keeping whichever revenue and whichever gross profit came last. A question
    about change across two years needs the ratio for each of them, and pairing
    two numbers that happen to be adjacent in the evidence store can pair them
    across years without saying so.
    """

    revenue: dict[str, tuple[Decimal, str]] = {}
    gross_profit: dict[str, tuple[Decimal, str]] = {}
    for item in evidence:
        record = getattr(item, "structured_record", None)
        if record is None or record.value is None:
            continue
        period = str(record.period or "")
        if not period:
            continue
        name = record.metric_name.strip().lower()
        if name in _REVENUE_NAMES:
            revenue.setdefault(period, (Decimal(str(record.value)), item.id))
        elif name in _GROSS_PROFIT_NAMES:
            gross_profit.setdefault(period, (Decimal(str(record.value)), item.id))

    derived: list[dict[str, Any]] = []
    for period in sorted(set(revenue) & set(gross_profit)):
        revenue_value, revenue_id = revenue[period]
        profit_value, profit_id = gross_profit[period]
        if not revenue_value:
            continue
        margin = profit_value / revenue_value * 100
        derived.append(
            {
                "label": "毛利率",
                "period": period,
                "numerator": f"{profit_value:,.0f}",
                "denominator": f"{revenue_value:,.0f}",
                "value": f"{margin:.2f}%",
                "evidence_ids": [profit_id, revenue_id],
            }
        )
    return derived
