from __future__ import annotations

import re
from typing import Any

from deepresearch_agent.domains.finance.vocabulary import canonical_metric


_COMPARISON_RE = re.compile(r"同比|较上年|比上年|上年同期|较去年|比去年")


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
