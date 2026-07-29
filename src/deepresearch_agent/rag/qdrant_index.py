from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import httpx


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    document_version_id: str
    effective_date: str
    char_start: int
    char_end: int
    vector: list[float]


class QdrantIndex:
    """Small fail-closed REST adapter for one derived-vector collection."""

    fidelity = "real"

    def __init__(
        self, *, url: str, api_key: str, collection: str, timeout_seconds: float = 10.0
    ) -> None:
        if not url or not api_key or not collection:
            raise ValueError("Qdrant url, API key, and collection are required")
        self.base_url = url.rstrip("/")
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self.headers = {"api-key": api_key}

    @staticmethod
    def point_id(*, chunk_id: str, model: str, chunker_version: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"{chunk_id}:{model}:{chunker_version}"))

    def ensure_collection(self, *, dimensions: int, index_version: str) -> None:
        response = httpx.get(self._collection_url, headers=self.headers, timeout=self.timeout_seconds)
        if response.status_code == 404:
            created = httpx.put(
                self._collection_url,
                headers=self.headers,
                timeout=self.timeout_seconds,
                json={"vectors": {"size": dimensions, "distance": "Cosine", "on_disk": True}},
            )
            created.raise_for_status()
            return
        response.raise_for_status()
        config = response.json().get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
        if int(config.get("size", -1)) != dimensions:
            raise ValueError("Qdrant collection dimensions do not match index configuration")
        sample = httpx.post(
            f"{self._collection_url}/points/scroll",
            headers=self.headers,
            timeout=self.timeout_seconds,
            json={"limit": 1, "with_payload": ["index_version"], "with_vector": False},
        )
        sample.raise_for_status()
        points = sample.json().get("result", {}).get("points", [])
        if points:
            existing = points[0].get("payload", {}).get("index_version")
            if existing != index_version:
                raise ValueError("Qdrant collection index_version does not match index configuration")

    def upsert(
        self, *, chunks: list[IndexedChunk], model: str, chunker_version: str, index_version: str
    ) -> int:
        if not chunks:
            return 0
        dimensions = len(chunks[0].vector)
        if dimensions < 1 or any(len(chunk.vector) != dimensions for chunk in chunks):
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
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "index_version": index_version,
                },
            }
            for chunk in chunks
        ]
        response = httpx.put(
            f"{self._collection_url}/points",
            headers=self.headers,
            params={"wait": "true"},
            timeout=self.timeout_seconds,
            json={"points": points},
        )
        response.raise_for_status()
        return len(points)

    @property
    def _collection_url(self) -> str:
        return f"{self.base_url}/collections/{self.collection}"
