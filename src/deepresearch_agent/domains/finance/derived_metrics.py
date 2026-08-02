"""Finance-owned deterministic derived metrics for reader reports."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def reader_derived_metrics(evidence: list[Any]) -> list[dict[str, Any]]:
    revenue = gross_profit = None
    for item in evidence:
        record = getattr(item, "structured_record", None)
        if record is None or record.value is None:
            continue
        name = record.metric_name.lower()
        if name in {"营业收入", "revenue"}:
            revenue = (record.value, item.id)
        elif name in {"毛利", "grossprofit", "gross profit"}:
            gross_profit = (record.value, item.id)
    if revenue is None or gross_profit is None or not revenue[0]:
        return []
    margin = Decimal(str(gross_profit[0])) / Decimal(str(revenue[0])) * 100
    return [{
        "label": "毛利率",
        "numerator": f"{Decimal(str(gross_profit[0])):,.0f}",
        "denominator": f"{Decimal(str(revenue[0])):,.0f}",
        "value": f"{margin:.2f}%",
        "evidence_ids": [gross_profit[1], revenue[1]],
    }]
