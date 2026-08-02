"""A no-domain pack used to prove generic workflow composition.

It intentionally offers no metric vocabulary, disclosure policy, skill, or
numeric interpretation.  It is not a product domain; it is a fail-closed
composition test fixture for the harness boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from deepresearch_agent.domains.protocols import RetrievalFilterValues
from deepresearch_agent.reporting.grounded_facts import GroundedFactBatch


@dataclass(frozen=True)
class _NullRenderer:
    def render(self, _state: Any) -> GroundedFactBatch:
        return GroundedFactBatch(required_labels=(), claims=(), gaps=())

    def is_supported(self, _text: str, _evidence: list[Any], _state: Any, *, labels: set[str]) -> bool:
        return not labels


@dataclass(frozen=True)
class _NullTableExtractors:
    def authoritative_backfills(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    def merge_authoritative_evidence(self, evidence: list[Any], _backfills: list[Any]) -> list[Any]:
        return evidence


@dataclass(frozen=True)
class _NullNumericChecker:
    def check(self, _state: Any) -> list[Any]:
        return []


@dataclass(frozen=True)
class _NullCitationPolicy:
    def has_numeric_mismatch(self, _claim_text: str, _cited_evidence: list[Any], *, required_metrics: set[str] | None = None) -> bool:
        return bool(required_metrics)

    def is_main_business_margin_dimension(self, _dimension: str | None) -> bool:
        return False


class NullDomainPack:
    """Explicitly capability-empty pack for a generic offline workflow."""

    name = "null"

    def canonical_metric(self, value: str | None) -> str:
        return (value or "").strip()

    def parse_period(self, _value: str | None) -> str | None:
        return None

    def amount_units(self) -> Mapping[str, Decimal]:
        return {}

    def structured_metric_aliases(self) -> Mapping[str, str]:
        return {}

    def fixture_metric_aliases(self) -> Mapping[str, str]:
        return {}

    def default_structured_metrics(self) -> tuple[str, ...]:
        return ()

    def structured_metric_unit(self, _metric_name: str) -> str | None:
        return None

    def equity_exchange_label(self) -> str:
        return "unknown"

    def structured_issuer_aliases(self) -> Mapping[str, str]:
        return {}

    def structured_xbrl_concepts(self) -> Mapping[str, tuple[str, ...]]:
        return {}

    def primary_source_keyword(self, *, financial_intent: bool) -> str:
        return "notice" if financial_intent else "source"

    def primary_source_terms(self, *, financial_intent: bool) -> tuple[str, ...]:
        return ()

    def grounded_fact_renderer(self) -> _NullRenderer:
        return _NullRenderer()

    def table_extractors(self) -> _NullTableExtractors:
        return _NullTableExtractors()

    def metric_table_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / "data/mock_data/null_metric_table.json"

    def metric_claim_pattern(self) -> re.Pattern[str]:
        return re.compile(r"(?!)")

    def comparison_observed(self, _evidence: Any) -> bool:
        return False

    def evidence_matches_metric(self, _evidence: Any, _required_metric: str) -> bool:
        return False

    def demo_numeric_claim(self, _claims: list[Any]) -> None:
        return None

    def demo_scope_claim(self, _claims: list[Any], _numeric_change: Any | None) -> None:
        return None

    def scope_change_summary(self, label: str) -> str:
        return label

    def is_full_annual_report_query(self, _keyword: str) -> bool:
        return False

    def is_full_annual_report_title(self, _title: str) -> bool:
        return False

    def report_year_from_title(self, _title: str) -> int | None:
        return None

    def is_amount_unit(self, _value: str) -> bool:
        return False

    def golden_type_distribution(self) -> Mapping[str, int]:
        return {}

    def evidence_explains_change(self, _text: str) -> bool:
        return False

    def document_type_tokens(self) -> tuple[str, ...]:
        return ()

    def document_type_for_direction(self, _direction: str) -> str:
        return "source"

    def metric_gap_direction(self) -> str:
        return "gather source evidence"

    def evidence_gap_direction(self) -> str:
        return "gather independent evidence"

    def metric_skill_applicable(self, _metadata: Any, _context: str) -> bool:
        return False

    def numeric_consistency_checker(self, _metric_table: dict[str, Any], *, relative_tolerance: float, absolute_tolerance: float) -> _NullNumericChecker:
        del relative_tolerance, absolute_tolerance
        return _NullNumericChecker()

    def numeric_citation_policy(self) -> _NullCitationPolicy:
        return _NullCitationPolicy()

    def deterministic_plan(self, _topic: str, _depth_level: int) -> None:
        return None

    def propagate_plan_identity(self, plan: Any, _topic: str) -> Any:
        return plan

    def valid_structured_request(self, _request: Any) -> bool:
        return False

    def retrieval_filter_values(self, _query: str) -> RetrievalFilterValues:
        return RetrievalFilterValues()

    def expand_retrieval_query(self, query: str) -> str:
        return query
