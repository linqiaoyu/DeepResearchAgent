from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from deepresearch_agent.reporting import GroundedFactRenderer


class DomainPack(Protocol):
    """Explicit domain boundary used by generic orchestration code."""

    name: str

    def canonical_metric(self, value: str | None) -> str: ...

    def parse_period(self, value: str | None) -> str | None: ...

    def amount_units(self) -> Mapping[str, Decimal]: ...

    def primary_source_keyword(self, *, financial_intent: bool) -> str: ...

    def grounded_fact_renderer(self) -> GroundedFactRenderer: ...
