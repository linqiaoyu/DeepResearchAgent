from __future__ import annotations

from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from deepresearch_agent.schemas import StrictModel

WriteT = TypeVar("WriteT")
QueryT = TypeVar("QueryT")
ResultT = TypeVar("ResultT")

MemoryLifecycle = Literal["run", "cross_run", "persistent"]


class MemoryScope(StrictModel):
    """Explicit ownership boundary; implementations must never cross it."""

    namespace: str
    domain: str
    research_id: str | None = None


@runtime_checkable
class MemoryStore(Protocol, Generic[WriteT, QueryT, ResultT]):
    """Forward contract shared by episodic, semantic and 016 procedural memory."""

    scope: MemoryScope
    lifecycle: MemoryLifecycle

    def write(self, record: WriteT) -> None:
        ...

    def query(self, query: QueryT) -> ResultT:
        ...
