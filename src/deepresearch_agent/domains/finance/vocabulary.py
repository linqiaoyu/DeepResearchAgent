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
    "毛利": "毛利",
    "毛利率": "主营业务毛利率",
    "主营业务毛利率": "主营业务毛利率",
}
def metrics_mentioned(text: str, required: set[str]) -> set[str]:
    """Which required metrics a sentence talks about, by surface form.

    R100: the renderer decided whether an analysis claim was on topic by asking
    whether it cited a key finding's evidence. When every key finding is a gap
    notice there is no such evidence, so four claims about this question's own
    revenue and margin drivers were filed as off-topic and deleted. A sentence
    naming the metric is on topic whatever it cites, and the alias table already
    knows that `毛利率` and `整车毛利率` are about `主营业务毛利率`.
    """

    if not text or not required:
        return set()
    mentioned: set[str] = set()
    for surface, canonical in METRIC_ALIASES.items():
        if canonical in required and surface in text:
            mentioned.add(canonical)
    return mentioned


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
# Standard US-GAAP concepts used when the finance pack routes a 20-F issuer to
# the SEC Company Facts provider.  This remains a finance-domain vocabulary,
# not a generic harness decision.
SEC_COMPANYFACTS_CONCEPTS = {
    "营业收入": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "毛利": ("GrossProfit",),
    "归母净利润": ("NetIncomeLoss",),
    "净利润": ("ProfitLoss", "NetIncomeLoss"),
    "每股收益": ("EarningsPerShareDiluted",),
}
SEC_COMPANYFACTS_UNSUPPORTED_METRICS = ("主营业务毛利率", "市盈率")
#: R102: what a metric can be computed from when no source publishes it directly.
#: The filer publishes `GrossProfit` and revenue for every period it reports, and
#: `derived_metrics.reader_derived_metrics` has always known how to divide them --
#: but nothing ever asked for `毛利`, because requests were built from the words
#: in the question and `主营业务毛利率` is listed as unsupported. The reader was
#: told the metric could be computed and was not.
#:
#: Only exact, deterministic identities belong here. A ratio whose inputs need an
#: estimate is not a derivation, and this table is not the place to pretend
#: otherwise.
METRIC_COMPONENTS = {
    "主营业务毛利率": ("营业收入", "毛利"),
}
FINANCIAL_INTENT_TERMS = (
    "annual report",
    "revenue",
    "gross profit",
    "gross margin",
    "financial results",
    "年报",
    "营收",
    "营业收入",
    "毛利",
    "毛利率",
    "净利润",
)
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
