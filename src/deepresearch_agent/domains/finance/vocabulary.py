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
STRUCTURED_METRIC_ALIASES = {
    # AKShare 1.18.64 exposes the annual-revenue row as 营业总收入.
    "营业总收入": "营业收入",
    "营收": "营业收入",
    "归母净利润": "归母净利润",
    "净利润": "净利润",
    "扣非净利润": "扣非净利润",
    "毛利率": "毛利率",
}
FIXTURE_METRIC_ALIASES = {
    "营业总收入": "营业收入",
    "营收": "营业收入",
}
DEFAULT_STRUCTURED_METRICS = tuple(STRUCTURED_METRIC_ALIASES.values())
STRUCTURED_METRIC_UNITS = {
    "营业收入": "元",
    "归母净利润": "元",
    "净利润": "元",
    "扣非净利润": "元",
    "毛利率": "%",
    "主营业务毛利率": "%",
    "每股收益": "元/股",
    "市盈率": "倍",
    "存货周转率": "次",
}
MAINLAND_EQUITY_EXCHANGE = "A股"
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def canonical_metric(value: str | None) -> str:
    normalized = re.sub(r"[\s：:（）()]", "", value or "")
    return METRIC_ALIASES.get(normalized, normalized)


def parse_period(value: str | None) -> str | None:
    if not value:
        return None
    rendered = str(value).strip()
    if re.fullmatch(r"20\d{6}", rendered):
        return rendered[:4]
    match = _YEAR_RE.search(rendered)
    return match.group(1) if match else None
