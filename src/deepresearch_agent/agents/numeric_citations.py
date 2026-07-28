"""Backward-compatible facade for the former numeric-citation module.

The finance implementation lives in the domain pack. New orchestration code
must receive its policy through ``DomainPack`` instead of importing this shim.
"""

from __future__ import annotations

from typing import Sequence

from deepresearch_agent.domains.protocols import NumericCitationPolicy
from deepresearch_agent.schemas import Evidence


def has_financial_numeric_mismatch(
    claim_text: str,
    cited_evidence: Sequence[Evidence],
    *,
    policy: NumericCitationPolicy,
    required_metrics: set[str] | None = None,
) -> bool:
    return policy.has_numeric_mismatch(
        claim_text,
        cited_evidence,
        required_metrics=required_metrics,
    )


def is_main_business_margin_dimension(
    dimension: str | None, *, policy: NumericCitationPolicy
) -> bool:
    return policy.is_main_business_margin_dimension(dimension)
