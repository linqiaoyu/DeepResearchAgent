from __future__ import annotations

from datetime import date

from pydantic import Field

from deepresearch_agent.context import PackResult, pack_evidence
from deepresearch_agent.memory.protocols import MemoryLifecycle, MemoryScope
from deepresearch_agent.schemas import Evidence, StrictModel


class WorkingMemoryWrite(StrictModel):
    research_id: str
    evidence: list[Evidence] = Field(default_factory=list)
    as_of: date
    provenance_refs: tuple[str, ...] = Field(min_length=1)


class WorkingMemoryQuery(StrictModel):
    research_id: str
    topic: str
    budget: int
    as_of: date | None = None


class ContextWorkingMemory:
    """Run-scoped adapter over the existing deterministic context packer."""

    lifecycle: MemoryLifecycle = "run"

    def __init__(self, scope: MemoryScope | None = None) -> None:
        self.scope = scope or MemoryScope(
            namespace="working",
            domain="finance",
        )
        self._evidence_by_run: dict[str, list[Evidence]] = {}

    def write(self, record: WorkingMemoryWrite) -> None:
        if self.scope.research_id and record.research_id != self.scope.research_id:
            raise ValueError("Working memory write crosses run scope")
        self._evidence_by_run[record.research_id] = list(record.evidence)

    def query(self, query: WorkingMemoryQuery) -> PackResult:
        if self.scope.research_id and query.research_id != self.scope.research_id:
            raise ValueError("Working memory query crosses run scope")
        evidence = self._evidence_by_run.get(query.research_id, [])
        return pack_evidence(
            evidence,
            topic=query.topic,
            budget=query.budget,
            as_of=query.as_of,
        )
