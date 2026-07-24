from __future__ import annotations

from datetime import date

from deepresearch_agent.memory.protocols import MemoryLifecycle, MemoryScope
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
    """Deterministic cross-run lookup keyed by question_id + as_of."""

    lifecycle: MemoryLifecycle = "cross_run"

    def __init__(self, scope: MemoryScope | None = None) -> None:
        self.scope = scope or MemoryScope(
            namespace="episodic",
            domain="finance",
        )
        self._records: dict[tuple[str, date], EpisodicRecord] = {}

    def write(self, record: EpisodicRecord) -> None:
        key = (
            record.snapshot.question_id,
            record.snapshot.as_of,
        )
        self._records[key] = record

    def query(self, query: EpisodicQuery) -> list[EpisodicRecord]:
        records = [
            record
            for (question_id, as_of), record in self._records.items()
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
