from __future__ import annotations

from datetime import date

from deepresearch_agent.memory.protocols import (
    MemoryLifecycle,
    MemoryRecordStore,
    MemoryScope,
)
from deepresearch_agent.storage.protocol import MemoryRecord
from deepresearch_agent.research_snapshot import ResearchSnapshot
from deepresearch_agent.schemas import StrictModel


class EpisodicRecord(StrictModel):
    """Index entry over existing snapshot and trajectory artifact formats."""

    snapshot: ResearchSnapshot
    trajectory_ref: str | None = None


class EpisodicQuery(StrictModel):
    question_id: str
    as_of: date | None = None


class EpisodicMemory:
    """Deterministic cross-run lookup keyed by question_id + as_of.

    R122: ``lifecycle`` said ``cross_run`` while the implementation was an
    in-process dict, so a second run started empty and `PRIOR_MEMORY_ENABLED`
    read nothing however many runs preceded it. Given a store, the dict becomes
    a write-through cache over a durable row and the declared lifecycle is true.
    Without one the old behaviour is unchanged, which keeps every existing
    caller working.
    """

    lifecycle: MemoryLifecycle = "cross_run"

    def __init__(
        self,
        scope: MemoryScope | None = None,
        store: MemoryRecordStore | None = None,
    ) -> None:
        self.scope = scope or MemoryScope(
            namespace="episodic",
            domain="finance",
        )
        self.store = store
        self._records: dict[tuple[str, date], EpisodicRecord] = {}

    def write(self, record: EpisodicRecord) -> None:
        key = (
            record.snapshot.question_id,
            record.snapshot.as_of,
        )
        self._records[key] = record
        if self.store is not None:
            self.store.write_memory_record(
                MemoryRecord(
                    namespace=self.scope.namespace,
                    scope_key=record.snapshot.question_id,
                    record_id=(
                        f"{record.snapshot.as_of.isoformat()}|"
                        f"{record.snapshot.manifest_ref}"
                    ),
                    payload=record.model_dump_json(),
                )
            )

    def _durable(self, question_id: str) -> list[EpisodicRecord]:
        if self.store is None:
            return []
        return [
            EpisodicRecord.model_validate_json(row.payload)
            for row in self.store.list_memory_records(
                self.scope.namespace, question_id
            )
        ]

    def query(self, query: EpisodicQuery) -> list[EpisodicRecord]:
        merged: dict[tuple[str, date], EpisodicRecord] = {
            (item.snapshot.question_id, item.snapshot.as_of): item
            for item in self._durable(query.question_id)
        }
        merged.update(self._records)
        records = [
            record
            for (question_id, as_of), record in merged.items()
            if question_id == query.question_id
            and (query.as_of is None or as_of == query.as_of)
        ]
        return sorted(
            records,
            key=lambda item: (
                item.snapshot.as_of,
                item.snapshot.manifest_ref,
                item.trajectory_ref or "",
            ),
        )
