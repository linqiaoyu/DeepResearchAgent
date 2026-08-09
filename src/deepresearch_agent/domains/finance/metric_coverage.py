from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from deepresearch_agent.domains.finance.vocabulary import canonical_metric


_COMPARISON_RE = re.compile(r"同比|较上年|比上年|上年同期|较去年|比去年")
_PERIOD_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
#: The scales that make two published amounts comparable at all. They are
#: deliberately not made equal: `324.96 亿元` is a rounding of a filing's exact
#: 元 figure, and collapsing the two would hide which precision a source
#: actually published.
_AMOUNT_SCALES = {
    "元": Decimal(1),
    "万元": Decimal(10**4),
    "亿元": Decimal(10**8),
}


def coverage_figure_key(evidence: Any) -> tuple[str, str]:
    """Identify one published figure, so a restatement of it is not a second.

    R109: the first live 长江电力 round rendered 指标覆盖状态 for 归母净利润 as
    one 1,500-character line carrying every matching evidence id -- the same
    three figures restated thirteen times between them. Deduplication needs to
    know what makes two amounts the same amount, which is a domain question:
    the reporter has no business knowing what 亿元 is.
    """

    record = getattr(evidence, "structured_record", None)
    fields = getattr(evidence, "numeric_fields", None)
    raw_period = str(
        (record.period if record else fields.period if fields else "") or ""
    )
    match = _PERIOD_YEAR_RE.search(raw_period)
    year = match.group(1) if match else raw_period
    value = record.value if record else fields.value if fields else None
    unit = (record.unit if record else fields.unit if fields else "") or ""
    if value is None:
        # Nothing comparable: keep it rather than dedup on an absent figure.
        return (year, str(getattr(evidence, "id", "")))
    scale = _AMOUNT_SCALES.get(unit)
    if scale is None:
        return (year, f"{value}{unit}")
    return (year, format(Decimal(str(value)) * scale, "f"))


def comparison_observed(evidence: Any) -> bool:
    return bool(_COMPARISON_RE.search(f"{evidence.claim}\n{evidence.extract_text}"))


def evidence_matches_metric(evidence: Any, required_metric: str) -> bool:
    evidence_metric = (
        evidence.structured_record.metric_name
        if evidence.structured_record
        else evidence.numeric_fields.metric_name
        if evidence.numeric_fields
        else None
    )
    canonical = canonical_metric(evidence_metric)
    if canonical != required_metric:
        # R108: `毛利率` canonicalises to itself now, so a margin that *is*
        # main-business no longer arrives under the strict name -- it arrives as
        # 毛利率 carrying a main-business dimension such as 酒类. What makes such
        # a record answer 主营业务毛利率 has always been that dimension, and the
        # test for it is below; returning early here put it out of reach and
        # dropped a filing's own 酒类毛利率 row.
        if not (required_metric == "主营业务毛利率" and canonical == "毛利率"):
            return False
    if required_metric != "主营业务毛利率":
        return True
    normalized_metric = re.sub(r"[\s：:（）()]", "", evidence_metric or "")
    if evidence.structured_record and normalized_metric == "主营业务毛利率":
        return True
    dimension = (
        evidence.structured_record.dimension
        if evidence.structured_record
        else evidence.numeric_fields.dimension
        if evidence.numeric_fields
        else None
    )
    from deepresearch_agent.domains.finance.numeric_citations import (
        is_main_business_margin_dimension,
    )

    return is_main_business_margin_dimension(dimension)
