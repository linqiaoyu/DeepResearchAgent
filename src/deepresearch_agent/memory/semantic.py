from __future__ import annotations

import hashlib
from datetime import date

from pydantic import Field

from deepresearch_agent.memory.protocols import (
    MemoryLifecycle,
    MemoryRecordStore,
    MemoryScope,
)
from deepresearch_agent.schemas import StrictModel
from deepresearch_agent.storage.protocol import MemoryRecord


class SemanticFact(StrictModel):
    entity: str
    normalized_metric: str
    period: str
    scope: str
    value: float | str
    unit: str | None = None
    source_urls: list[str] = Field(min_length=1)
    as_of: date
    confidence: float = Field(ge=0, le=1)

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.entity,
            self.normalized_metric,
            self.period,
            self.scope,
        )


class SemanticQuery(StrictModel):
    entity: str | None = None
    normalized_metric: str | None = None
    period: str | None = None
    scope: str | None = None


class SemanticSeries(StrictModel):
    entity: str
    normalized_metric: str
    period: str
    scope: str
    observations: list[SemanticFact] = Field(default_factory=list)


class SemanticMemory:
    """Exact four-key finance fact index with deterministic subset queries."""

    def __init__(
        self,
        scope: MemoryScope | None = None,
        store: MemoryRecordStore | None = None,
    ) -> None:
        self.scope = scope or MemoryScope(
            namespace="semantic",
            domain="finance",
        )
        self.store = store
        self.lifecycle: MemoryLifecycle = (
            "persistent" if store is not None else "cross_run"
        )
        self._facts: dict[
            tuple[str, str, str, str],
            dict[tuple[date, str, str], SemanticFact],
        ] = {}

    def write(self, record: SemanticFact) -> None:
        observations = self._facts.setdefault(record.key, {})
        observation_key = (
            record.as_of,
            str(record.value),
            "\n".join(sorted(record.source_urls)),
        )
        observations[observation_key] = record
        if self.store is not None:
            payload = record.model_dump_json()
            self.store.write_memory_record(
                MemoryRecord(
                    namespace=self.scope.storage_namespace,
                    scope_key="facts",
                    record_id=hashlib.sha256(
                        payload.encode("utf-8")
                    ).hexdigest(),
                    payload=payload,
                )
            )

    def query(self, query: SemanticQuery) -> list[SemanticSeries]:
        facts = {
            key: dict(indexed)
            for key, indexed in self._facts.items()
        }
        if self.store is not None:
            for row in self.store.list_memory_records(
                self.scope.storage_namespace,
                "facts",
            ):
                fact = SemanticFact.model_validate_json(row.payload)
                facts.setdefault(fact.key, {})[
                    (
                        fact.as_of,
                        str(fact.value),
                        "\n".join(sorted(fact.source_urls)),
                    )
                ] = fact
        series: list[SemanticSeries] = []
        for key, indexed in facts.items():
            if not self._matches(key, query):
                continue
            observations = sorted(
                indexed.values(),
                key=lambda item: (
                    item.as_of,
                    str(item.value),
                    tuple(sorted(item.source_urls)),
                    item.confidence,
                ),
            )
            series.append(
                SemanticSeries(
                    entity=key[0],
                    normalized_metric=key[1],
                    period=key[2],
                    scope=key[3],
                    observations=observations,
                )
            )
        return sorted(
            series,
            key=lambda item: (
                item.entity,
                item.normalized_metric,
                item.period,
                item.scope,
            ),
        )

    def _matches(
        self,
        key: tuple[str, str, str, str],
        query: SemanticQuery,
    ) -> bool:
        expected = (
            query.entity,
            query.normalized_metric,
            query.period,
            query.scope,
        )
        return all(
            value is None or value == actual
            for actual, value in zip(key, expected, strict=True)
        )
