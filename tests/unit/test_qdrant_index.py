from __future__ import annotations

import unittest
from unittest.mock import patch

from deepresearch_agent.rag.qdrant_index import IndexedChunk, QdrantIndex
from deepresearch_agent.tools import RunToolContext, ToolErrorKind, ToolExecutionError


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
    def test_request_budget_refuses_qdrant_before_http(self) -> None:
        context = RunToolContext.for_run(max_external_fetch_requests=0)
        index = QdrantIndex(
            url="https://qdrant.test",
            api_key="test",
            collection="collection",
            context=context,
        )
        with patch("deepresearch_agent.rag.qdrant_index.httpx.get") as get:
            with self.assertRaises(ToolExecutionError) as captured:
                index.collection_status()
        self.assertEqual(captured.exception.kind, ToolErrorKind.BUDGET_EXCEEDED)
        get.assert_not_called()

    def test_collection_status_is_read_only_and_allows_local_no_auth(self) -> None:
        index = QdrantIndex(url="http://127.0.0.1:6333", api_key="", collection="collection")
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.get",
            return_value=Response(status_code=404),
        ) as get:
            self.assertEqual(index.collection_status(), "missing")

        self.assertEqual(get.call_count, 1)

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
            side_effect=[Response(status_code=200)] * 6,
        ) as put:
            self.assertEqual(
                index.upsert(chunks=[chunk], model="model", chunker_version="v1", index_version="idx-v1"),
                1,
            )

        self.assertEqual(put.call_args_list[1].kwargs["json"], {"field_name": "published_at", "field_schema": "datetime"})
        self.assertEqual(put.call_args_list[2].kwargs["json"], {"field_name": "index_version", "field_schema": "keyword"})
        self.assertEqual(put.call_args_list[3].kwargs["json"], {"field_name": "entity_id", "field_schema": "keyword"})
        self.assertEqual(put.call_args_list[4].kwargs["json"], {"field_name": "period_label", "field_schema": "keyword"})
        payload = put.call_args_list[5].kwargs["json"]["points"][0]["payload"]
        self.assertEqual(set(payload), {"chunk_id", "document_version_id", "effective_date", "published_at", "char_start", "char_end", "index_version", "entity_id", "period_label"})
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

    def test_query_sends_only_filterable_payload_and_returns_chunk_ids(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.get",
            return_value=Response(
                status_code=200,
                payload={"result": {"config": {"params": {"vectors": {"size": 2}}}}},
            ),
        ), patch(
            "deepresearch_agent.rag.qdrant_index.httpx.put",
            return_value=Response(status_code=200),
        ) as put, patch(
            "deepresearch_agent.rag.qdrant_index.httpx.post",
            side_effect=[
                Response(status_code=200, payload={"result": {"points": []}}),
                Response(status_code=200, payload={"result": {"points": [{"score": 0.8, "payload": {"chunk_id": "chunk-a"}}]}}),
            ],
        ) as post:
            hits = index.query(vector=[0.1, 0.2], as_of="2026-01-01", index_version="idx-v1", limit=3)

        self.assertEqual([(hit.chunk_id, hit.score) for hit in hits], [("chunk-a", 0.8)])
        self.assertEqual(put.call_count, 0)
        payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(payload["with_payload"], ["chunk_id"])
        self.assertNotIn("text", str(payload))
        self.assertEqual(payload["filter"]["must"][0]["key"], "published_at")

    def test_query_missing_collection_raises_without_put(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.get",
            return_value=Response(status_code=404),
        ), patch("deepresearch_agent.rag.qdrant_index.httpx.put") as put:
            with self.assertRaisesRegex(ToolExecutionError, "collection is missing"):
                index.query(vector=[0.1, 0.2], as_of="2026-01-01", index_version="idx-v1", limit=3)
        self.assertEqual(put.call_count, 0)

    def test_query_adds_entity_filter_when_requested(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        with patch("deepresearch_agent.rag.qdrant_index.httpx.get", return_value=Response(status_code=200, payload={"result": {"config": {"params": {"vectors": {"size": 2}}}}})), patch("deepresearch_agent.rag.qdrant_index.httpx.put", return_value=Response(status_code=200)), patch("deepresearch_agent.rag.qdrant_index.httpx.post", side_effect=[Response(status_code=200, payload={"result": {"points": []}}), Response(status_code=200, payload={"result": {"points": []}})]) as post:
            index.query(
                vector=[0.1, 0.2],
                as_of="2026-01-01",
                index_version="idx-v1",
                limit=3,
                entity_ids=("baba", "baba"),
                period_labels=("2024",),
            )

        must = post.call_args_list[1].kwargs["json"]["filter"]["must"]
        self.assertIn({"key": "entity_id", "match": {"any": ["baba"]}}, must)
        self.assertIn({"key": "period_label", "match": {"any": ["2024"]}}, must)

    def test_entity_payload_backfill_uses_stable_point_ids_without_text(self) -> None:
        index = QdrantIndex(url="https://qdrant.test", api_key="test", collection="collection")
        with patch(
            "deepresearch_agent.rag.qdrant_index.httpx.post",
            return_value=Response(status_code=200),
        ) as post:
            updated = index.set_filter_payload(
                chunk_ids=["chunk-a", "chunk-b"],
                payload={"entity_id": "baba", "period_label": "2024"},
                model="model",
                chunker_version="v1",
            )

        self.assertEqual(updated, 2)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["payload"], {"entity_id": "baba", "period_label": "2024"})
        self.assertEqual(len(payload["points"]), 2)
        self.assertNotIn("text", str(payload))


if __name__ == "__main__":
    unittest.main()
