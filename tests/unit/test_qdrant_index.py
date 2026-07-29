from __future__ import annotations

import unittest
from unittest.mock import patch

from deepresearch_agent.rag.qdrant_index import IndexedChunk, QdrantIndex


class Response:
    def __init__(self, *, status_code: int, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http={self.status_code}")

    def json(self) -> dict[str, object]:
        return self.payload


class QdrantIndexTests(unittest.TestCase):
    def test_point_id_is_stable_and_model_scoped(self) -> None:
        first = QdrantIndex.point_id(chunk_id="chunk", model="model-a", chunker_version="v1")
        self.assertEqual(
            first,
            QdrantIndex.point_id(chunk_id="chunk", model="model-a", chunker_version="v1"),
        )
        self.assertNotEqual(
            first,
            QdrantIndex.point_id(chunk_id="chunk", model="model-b", chunker_version="v1"),
        )

    def test_upsert_creates_collection_and_never_sends_chunk_text(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        chunk = IndexedChunk("chunk", "document-v1", "2026-01-01", 0, 9, [0.1, 0.2])
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.get",
            return_value=Response(status_code=404),
        ), patch(
            "deepresearch_agent.rag.qdrant_index.httpx.put",
            side_effect=[Response(status_code=200), Response(status_code=200)],
        ) as put:
            self.assertEqual(
                index.upsert(chunks=[chunk], model="model", chunker_version="v1", index_version="idx-v1"),
                1,
            )

        payload = put.call_args_list[1].kwargs["json"]["points"][0]["payload"]
        self.assertEqual(set(payload), {"chunk_id", "document_version_id", "effective_date", "char_start", "char_end", "index_version"})
        self.assertNotIn("text", payload)
        self.assertNotIn("content", payload)

    def test_dimension_mismatch_is_rejected_before_point_write(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.get",
            return_value=Response(
                status_code=200,
                payload={"result": {"config": {"params": {"vectors": {"size": 3}}}}},
            ),
        ), self.assertRaisesRegex(ValueError, "dimensions"):
            index.upsert(
                chunks=[IndexedChunk("chunk", "document-v1", "2026-01-01", 0, 9, [0.1, 0.2])],
                model="model",
                chunker_version="v1",
                index_version="idx-v1",
            )

    def test_existing_index_version_mismatch_is_rejected_before_point_write(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.get",
            return_value=Response(
                status_code=200,
                payload={"result": {"config": {"params": {"vectors": {"size": 2}}}}},
            ),
        ), patch(
            "deepresearch_agent.rag.qdrant_index.httpx.post",
            return_value=Response(
                status_code=200,
                payload={"result": {"points": [{"payload": {"index_version": "idx-old"}}]}},
            ),
        ), self.assertRaisesRegex(ValueError, "index_version"):
            index.upsert(
                chunks=[IndexedChunk("chunk", "document-v1", "2026-01-01", 0, 9, [0.1, 0.2])],
                model="model",
                chunker_version="v1",
                index_version="idx-new",
            )


if __name__ == "__main__":
    unittest.main()
