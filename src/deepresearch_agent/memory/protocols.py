from __future__ import annotations

from typing import Any, Generic, Literal, Protocol, TypeVar, runtime_checkable

from deepresearch_agent.schemas import StrictModel

WriteT = TypeVar("WriteT")
QueryT = TypeVar("QueryT")
ResultT = TypeVar("ResultT")

MemoryLifecycle = Literal["run", "cross_run", "persistent"]


class MemoryScope(StrictModel):
    """Explicit ownership boundary; implementations must never cross it."""

    namespace: str
    domain: str
    tenant_id: str = "default"
    research_id: str | None = None

    @property
    def storage_namespace(self) -> str:
        return f"{self.tenant_id}:{self.domain}:{self.namespace}"


@runtime_checkable
class MemoryRecordStore(Protocol):
    """The slice of ``StorageProtocol`` a durable memory needs.

    R122: narrowing it here keeps the memory layer independent of the storage
    backend and lets a test substitute one without a database.
    """

    def write_memory_record(self, record: Any) -> None: ...

    def list_memory_records(self, namespace: str, scope_key: str) -> list[Any]: ...


@runtime_checkable
class MemoryStore(Protocol, Generic[WriteT, QueryT, ResultT]):
    """Forward contract shared by episodic, semantic and 016 procedural memory."""

    scope: MemoryScope
    lifecycle: MemoryLifecycle

    def write(self, record: WriteT) -> None:
        ...

    def query(self, query: QueryT) -> ResultT:
        ...
