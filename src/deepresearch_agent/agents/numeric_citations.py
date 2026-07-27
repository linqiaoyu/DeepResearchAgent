"""Backward-compatible facade for the former numeric-citation module.

The finance implementation lives in the domain pack. New orchestration code
must receive its policy through ``DomainPack`` instead of importing this shim.
"""

from __future__ import annotations

from typing import Sequence

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import Evidence


def has_financial_numeric_mismatch(
    claim_text: str,
    cited_evidence: Sequence[Evidence],
    *,
    required_metrics: set[str] | None = None,
) -> bool:
    return load_domain_pack("finance").numeric_citation_policy().has_numeric_mismatch(
        claim_text,
        cited_evidence,
        required_metrics=required_metrics,
    )


def is_main_business_margin_dimension(dimension: str | None) -> bool:
    return load_domain_pack("finance").numeric_citation_policy().is_main_business_margin_dimension(
        dimension
    )
