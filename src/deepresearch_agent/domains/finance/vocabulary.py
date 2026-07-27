from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

METRIC_ALIASES = {
    "营收": "营业收入",
    "营业收入": "营业收入",
    "归母净利润": "归母净利润",
    "归属于母公司股东的净利润": "归母净利润",
    "归属于上市公司股东的净利润": "归母净利润",
    "毛利率": "主营业务毛利率",
    "主营业务毛利率": "主营业务毛利率",
}
AMOUNT_UNITS: Mapping[str, Decimal] = {
    "元": Decimal("1"),
    "千元": Decimal("1000"),
    "万元": Decimal("10000"),
    "百万元": Decimal("1000000"),
    "亿元": Decimal("100000000"),
}
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def canonical_metric(value: str | None) -> str:
    normalized = re.sub(r"[\s：:（）()]", "", value or "")
    return METRIC_ALIASES.get(normalized, normalized)


def parse_period(value: str | None) -> str:
    if not value:
        return ""
    rendered = str(value).strip()
    if re.fullmatch(r"20\d{6}", rendered):
        return rendered[:4]
    match = _YEAR_RE.search(rendered)
    return match.group(1) if match else ""
