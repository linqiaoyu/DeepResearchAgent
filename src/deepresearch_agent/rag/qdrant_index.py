from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from deepresearch_agent.tools import (
    ReliableToolExecutor,
    RunToolContext,
    ToolErrorKind,
    ToolExecutionError,
    ToolSpec,
)


QDRANT_HTTP_TOOL_SPEC = ToolSpec(
    name="qdrant_http",
    version="1",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    timeout_s=10.0,
    total_timeout_s=30.0,
    cost_class="free",
    idempotent=True,
    has_side_effect=True,
)


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    document_version_id: str
    effective_date: str
    char_start: int
    char_end: int
    vector: list[float]
    source_url: str
    published_at: str
    published_at_source: str
    index_version: str
    entity_id: str = ""


@dataclass(frozen=True)
class QdrantQueryHit:
    """A score and chunk identity returned by the derived vector index."""

    chunk_id: str
    score: float


class QdrantIndex:
    """Small fail-closed REST adapter for one derived-vector collection."""

    fidelity = "real"

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        collection: str,
        timeout_seconds: float = 10.0,
        executor: ReliableToolExecutor | None = None,
        context: RunToolContext | None = None,
    ) -> None:
        if not url or not collection:
            raise ValueError("Qdrant url and collection are required")
        self.base_url = url.rstrip("/")
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self.headers = {"api-key": api_key} if api_key else {}
        self._prepared_dimensions: int | None = None
        self.executor = executor or ReliableToolExecutor()
        self.context = context or RunToolContext.for_run()
        self.tool_spec = QDRANT_HTTP_TOOL_SPEC.model_copy(
            update={
                "timeout_s": timeout_seconds,
                "total_timeout_s": timeout_seconds * 3,
            }
        )

    def collection_status(self) -> str:
        """Return collection existence without creating or mutating it."""

        response = self._request(
            "get",
            self._collection_url,
            allowed_statuses=(404,),
        )
        if response.status_code == 404:
            return "missing"
        response.raise_for_status()
        return "exists"

    @staticmethod
    def point_id(*, chunk_id: str, model: str, chunker_version: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"{chunk_id}:{model}:{chunker_version}"))

    def ensure_collection(self, *, dimensions: int, index_version: str) -> None:
        if self._prepared_dimensions == dimensions:
            return
        response = self._request("get", self._collection_url, allowed_statuses=(404,))
        if response.status_code == 404:
            created = self._request(
                "put",
                self._collection_url,
                json={"vectors": {"size": dimensions, "distance": "Cosine", "on_disk": True}},
            )
            created.raise_for_status()
        else:
            response.raise_for_status()
            config = response.json().get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
            if int(config.get("size", -1)) != dimensions:
                raise ValueError("Qdrant collection dimensions do not match index configuration")
            sample = self._request(
                "post",
                f"{self._collection_url}/points/scroll",
                json={"limit": 1, "with_payload": ["index_version"], "with_vector": False},
            )
            sample.raise_for_status()
            points = sample.json().get("result", {}).get("points", [])
            if points:
                existing = points[0].get("payload", {}).get("index_version")
                if existing != index_version:
                    raise ValueError("Qdrant collection index_version does not match index configuration")
        for field_name, field_schema in (
            ("published_at", "datetime"),
            ("index_version", "keyword"),
            ("entity_id", "keyword"),
            ("period_label", "keyword"),
        ):
            indexed = self._request(
                "put",
                f"{self._collection_url}/index",
                json={"field_name": field_name, "field_schema": field_schema},
            )
            indexed.raise_for_status()
        self._prepared_dimensions = dimensions

    def upsert(
        self, *, chunks: list[IndexedChunk], model: str, chunker_version: str, index_version: str
    ) -> int:
        eligible = [
            chunk
            for chunk in chunks
            if chunk.published_at and chunk.published_at_source
        ]
        if not eligible:
            return 0
        if any(chunk.index_version != index_version for chunk in eligible):
            raise ValueError("IndexedChunk index_version does not match upsert configuration")
        if any(
            not chunk.document_version_id or not chunk.source_url
            for chunk in eligible
        ):
            raise ValueError(
                "IndexedChunk requires document_version_id and source_url"
            )
        dimensions = len(eligible[0].vector)
        if dimensions < 1 or any(len(chunk.vector) != dimensions for chunk in eligible):
            raise ValueError("Qdrant batch contains inconsistent vector dimensions")
        self.ensure_collection(dimensions=dimensions, index_version=index_version)
        points = [
            {
                "id": self.point_id(chunk_id=chunk.chunk_id, model=model, chunker_version=chunker_version),
                "vector": chunk.vector,
                "payload": {
                    "chunk_id": chunk.chunk_id,
                    "document_version_id": chunk.document_version_id,
                    "effective_date": chunk.effective_date,
                    "published_at": chunk.published_at,
                    "published_at_source": chunk.published_at_source,
                    "source_url": chunk.source_url,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "index_version": index_version,
                    "entity_id": chunk.entity_id,
                    "period_label": chunk.effective_date[:4],
                },
            }
            for chunk in eligible
        ]
        response = self._request(
            "put",
            f"{self._collection_url}/points",
            params={"wait": "true"},
            json={"points": points},
        )
        response.raise_for_status()
        return len(points)

    def query(
        self,
        *,
        vector: list[float],
        as_of: str,
        index_version: str | None,
        limit: int,
        entity_ids: tuple[str, ...] = (),
        period_labels: tuple[str, ...] = (),
    ) -> list[QdrantQueryHit]:
        """Query only payload identities; canonical chunk text stays in StorageProtocol."""

        if not vector or limit < 1:
            return []
        if index_version is None:
            raise ValueError("Qdrant queries require an index_version")
        self._verify_query_collection(dimensions=len(vector), index_version=index_version)
        must = [{"key": "published_at", "range": {"lte": as_of}}]
        must.append({"key": "index_version", "match": {"value": index_version}})
        if entity_ids:
            must.append({"key": "entity_id", "match": {"any": sorted(set(entity_ids))}})
        if period_labels:
            must.append({"key": "period_label", "match": {"any": sorted(set(period_labels))}})
        response = self._request(
            "post",
            f"{self._collection_url}/points/query",
            json={
                "query": vector,
                "limit": limit,
                "filter": {"must": must},
                "with_payload": ["chunk_id"],
                "with_vector": False,
            },
        )
        response.raise_for_status()
        points = response.json().get("result", {}).get("points", [])
        hits: list[QdrantQueryHit] = []
        for point in points:
            payload = point.get("payload", {})
            chunk_id = payload.get("chunk_id")
            if isinstance(chunk_id, str):
                hits.append(QdrantQueryHit(chunk_id=chunk_id, score=float(point["score"])))
        return hits

    def _verify_query_collection(self, *, dimensions: int, index_version: str) -> None:
        """Validate a prebuilt collection without creating indexes or collections."""

        response = self._request("get", self._collection_url, allowed_statuses=(404,))
        if response.status_code == 404:
            raise ToolExecutionError(
                ToolErrorKind.NOT_FOUND,
                f"Qdrant collection is missing: {self.collection}",
            )
        response.raise_for_status()
        config = response.json().get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
        if int(config.get("size", -1)) != dimensions:
            raise ToolExecutionError(
                ToolErrorKind.PERMANENT,
                "Qdrant collection dimensions do not match query vector dimensions",
            )
        sample = self._request(
            "post",
            f"{self._collection_url}/points/scroll",
            json={"limit": 1, "with_payload": ["index_version"], "with_vector": False},
        )
        sample.raise_for_status()
        points = sample.json().get("result", {}).get("points", [])
        if points and points[0].get("payload", {}).get("index_version") != index_version:
            raise ToolExecutionError(
                ToolErrorKind.PERMANENT,
                "Qdrant collection index_version does not match query configuration",
            )

    def set_filter_payload(
        self,
        *,
        chunk_ids: list[str],
        payload: dict[str, str],
        model: str,
        chunker_version: str,
    ) -> int:
        """Backfill filter-only fields without re-embedding text."""

        if not chunk_ids:
            return 0
        if not payload or any(not key or not value for key, value in payload.items()):
            raise ValueError("payload backfill requires non-empty filter fields")
        point_ids = [
            self.point_id(chunk_id=chunk_id, model=model, chunker_version=chunker_version)
            for chunk_id in chunk_ids
        ]
        response = self._request(
            "post",
            f"{self._collection_url}/points/payload",
            params={"wait": "true"},
            json={"payload": payload, "points": point_ids},
        )
        response.raise_for_status()
        return len(point_ids)

    @property
    def _collection_url(self) -> str:
        return f"{self.base_url}/collections/{self.collection}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        allowed_statuses: tuple[int, ...] = (),
        **kwargs: Any,
    ) -> Any:
        """Execute one counted Qdrant request through the shared tool control."""

        def operation() -> Any:
            self.context.consume_external_request("fetch", tool=self.tool_spec.name)
            request = getattr(httpx, method)
            try:
                response = request(
                    url,
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
                if response.status_code not in allowed_statuses:
                    response.raise_for_status()
                return response
            except httpx.TimeoutException as exc:
                raise ToolExecutionError(ToolErrorKind.TIMEOUT, str(exc)) from exc
            except httpx.TransportError as exc:
                raise ToolExecutionError(ToolErrorKind.TRANSIENT, str(exc)) from exc

        result = self.executor.execute(
            self.tool_spec,
            operation,
            self.context,
            degrade=False,
            impact="Qdrant operation failed closed; canonical storage remains authoritative",
        )
        if not result.ok:
            assert result.error is not None
            raise ToolExecutionError(result.error.kind, result.error.message)
        return result.value
