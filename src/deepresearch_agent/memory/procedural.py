from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from deepresearch_agent.memory.protocols import (
    MemoryLifecycle,
    MemoryRecordStore,
    MemoryScope,
)
from deepresearch_agent.storage.protocol import MemoryRecord
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
    observed_as_of: date
    provenance_refs: tuple[str, ...] = Field(min_length=1)
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

    def __init__(
        self,
        scope: MemoryScope | None = None,
        store: MemoryRecordStore | None = None,
    ) -> None:
        self.scope = scope or MemoryScope(
            namespace="procedural",
            domain="finance",
        )
        self.store = store
        self.lifecycle: MemoryLifecycle = (
            "persistent" if store is not None else "cross_run"
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
        if self.store is not None:
            self.store.write_memory_record(
                MemoryRecord(
                    namespace=self.scope.storage_namespace,
                    scope_key=record.question_type,
                    record_id=(
                        f"{record.run_id}|{record.sub_question_id}|{record.iteration}"
                    ),
                    payload=record.model_dump_json(),
                )
            )

    def _durable(self, question_type: str) -> dict[tuple[str, str, str, int], ProceduralRecord]:
        if self.store is None:
            return {}
        rows = self.store.list_memory_records(
            self.scope.storage_namespace,
            question_type,
        )
        restored = [ProceduralRecord.model_validate_json(row.payload) for row in rows]
        return {
            (item.question_type, item.run_id, item.sub_question_id, item.iteration): item
            for item in restored
        }

    def query(self, query: ProceduralQuery) -> ProceduralHistory:
        merged = self._durable(query.question_type)
        merged.update(self._records)
        records = [
            item.model_copy(deep=True)
            for key, item in merged.items()
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
