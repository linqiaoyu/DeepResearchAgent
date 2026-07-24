from __future__ import annotations

from typing import Literal

from pydantic import Field

from deepresearch_agent.memory.protocols import (
    MemoryLifecycle,
    MemoryScope,
)
from deepresearch_agent.reflection import DeterministicReflectionSignals
from deepresearch_agent.schemas import StrictModel


class ProceduralSufficiencyResult(StrictModel):
    score: float = Field(ge=0, le=1)
    sufficient: bool
    gaps: tuple[str, ...] = ()


class ProceduralRecord(StrictModel):
    """Observed result of one strategy under one question type."""

    question_type: str
    strategy: tuple[str, ...]
    sufficiency_result: ProceduralSufficiencyResult
    reflection_signals: DeterministicReflectionSignals
    run_id: str
    sub_question_id: str
    iteration: int = Field(ge=0)
    validation_status: Literal[
        "fixture_observation",
        "real_world_validated",
    ] = "fixture_observation"


class ProceduralQuery(StrictModel):
    question_type: str


class ProceduralHistory(StrictModel):
    question_type: str
    records: list[ProceduralRecord] = Field(default_factory=list)


class ProceduralMemory:
    """Deterministic cross-run index over observed strategy effects.

    The store exposes history; it does not rank, adopt, forget, or compress
    strategies. Whether accumulated preferences improve real research is
    explicitly deferred to 019.
    """

    lifecycle: MemoryLifecycle = "cross_run"

    def __init__(self, scope: MemoryScope | None = None) -> None:
        self.scope = scope or MemoryScope(
            namespace="procedural",
            domain="finance",
        )
        self._records: dict[
            tuple[str, str, str, int],
            ProceduralRecord,
        ] = {}

    def write(self, record: ProceduralRecord) -> None:
        key = (
            record.question_type,
            record.run_id,
            record.sub_question_id,
            record.iteration,
        )
        self._records[key] = record.model_copy(deep=True)

    def query(self, query: ProceduralQuery) -> ProceduralHistory:
        records = [
            item.model_copy(deep=True)
            for key, item in self._records.items()
            if key[0] == query.question_type
        ]
        records.sort(
            key=lambda item: (
                item.question_type,
                item.strategy,
                item.run_id,
                item.sub_question_id,
                item.iteration,
                item.sufficiency_result.score,
            )
        )
        return ProceduralHistory(
            question_type=query.question_type,
            records=records,
        )
