from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from deepresearch_agent.schemas import Evidence, ResearchState


FactKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class GroundedReaderClaim:
    """Reader text built by code from typed Evidence, never by token copying."""

    text: str
    evidence_ids: tuple[str, ...]
    fact_keys: frozenset[FactKey]
    label: str


@dataclass(frozen=True)
class GroundedFactBatch:
    required_labels: tuple[str, ...]
    claims: tuple[GroundedReaderClaim, ...]
    gaps: tuple[str, ...]


class GroundedFactRenderer(Protocol):
    """Domain boundary for mechanically rendered reader-visible facts."""

    def render(
        self,
        state: ResearchState,
    ) -> GroundedFactBatch: ...

    def is_supported(
        self,
        text: str,
        evidence: list[Evidence],
        state: ResearchState,
        *,
        labels: set[str],
    ) -> bool: ...
