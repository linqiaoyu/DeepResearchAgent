from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from deepresearch_agent.reporting import GroundedFactRenderer


class TableExtractors(Protocol):
    """Domain-owned parsing and merge policy for authoritative tables."""

    def authoritative_backfills(
        self,
        research_id: str,
        sub_question: Any,
        sources: list[Any],
        *,
        rejections: list[Any],
    ) -> list[Any]: ...

    def merge_authoritative_evidence(
        self, evidence: list[Any], backfills: list[Any]
    ) -> list[Any]: ...


class DomainPack(Protocol):
    """Explicit domain boundary used by generic orchestration code."""

    name: str

    def canonical_metric(self, value: str | None) -> str: ...

    def parse_period(self, value: str | None) -> str | None: ...

    def amount_units(self) -> Mapping[str, Decimal]: ...

    def primary_source_keyword(self, *, financial_intent: bool) -> str: ...

    def grounded_fact_renderer(self) -> GroundedFactRenderer: ...

    def table_extractors(self) -> TableExtractors: ...

    def metric_table_path(self) -> Path: ...

    def numeric_consistency_checker(
        self,
        metric_table: dict[str, Any],
        *,
        relative_tolerance: float,
        absolute_tolerance: float,
    ) -> Any: ...
