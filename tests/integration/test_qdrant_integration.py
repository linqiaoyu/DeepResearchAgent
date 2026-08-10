from __future__ import annotations

import os
import unittest
from uuid import uuid4

from deepresearch_agent.rag.qdrant_index import IndexedChunk, QdrantIndex


@unittest.skipUnless(
    os.getenv("DEEPRESEARCH_QDRANT_URL"),
    "DEEPRESEARCH_QDRANT_URL not set",
)
class QdrantIntegrationTests(unittest.TestCase):
    """Exercise the vector index against a live service.

    Until R112 this file held a single assertion -- that asking for the
    collection returned "exists" or "missing" -- and no CI job ever supplied
    `DEEPRESEARCH_QDRANT_URL`, so even that never ran. The index had never
    executed against a real Qdrant. These tests drive the write and read paths
    it is actually used for, including the as-of filter that keeps a filing
    invisible until it was disclosed.
    """

    def _index(self, collection: str) -> QdrantIndex:
        return QdrantIndex(
            url=os.environ["DEEPRESEARCH_QDRANT_URL"],
            api_key=os.getenv("DEEPRESEARCH_QDRANT_API_KEY", ""),
            collection=collection,
        )

    def test_configured_service_accepts_collection_read(self) -> None:
        index = self._index(os.getenv("DEEPRESEARCH_QDRANT_COLLECTION", "deepresearch_evidence"))

        self.assertIn(index.collection_status(), {"exists", "missing"})

    def test_upsert_then_query_returns_the_indexed_chunk(self) -> None:
        index = self._index(f"contract_{uuid4().hex}")
        index_version = "test-index-v1"

        written = index.upsert(
            chunks=[
                IndexedChunk(
                    chunk_id="qdrant-chunk-a",
                    document_version_id="version-a",
                    effective_date="2024-12-31",
                    published_at="2025-04-10",
                    char_start=0,
                    char_end=10,
                    vector=[1.0, 0.0, 0.0, 0.0],
                    entity_id="alpha",
                ),
                IndexedChunk(
                    chunk_id="qdrant-chunk-b",
                    document_version_id="version-b",
                    effective_date="2024-12-31",
                    published_at="2025-04-10",
                    char_start=0,
                    char_end=10,
                    vector=[0.0, 1.0, 0.0, 0.0],
                    entity_id="beta",
                ),
            ],
            model="test-model",
            chunker_version="v1",
            index_version=index_version,
        )
        self.assertEqual(written, 2)
        self.assertEqual(index.collection_status(), "exists")

        hits = index.query(
            vector=[1.0, 0.0, 0.0, 0.0],
            as_of="2025-12-31",
            index_version=index_version,
            limit=5,
        )
        self.assertEqual([hit.chunk_id for hit in hits][:1], ["qdrant-chunk-a"])

        scoped = index.query(
            vector=[1.0, 0.0, 0.0, 0.0],
            as_of="2025-12-31",
            index_version=index_version,
            limit=5,
            entity_ids=("beta",),
        )
        self.assertEqual([hit.chunk_id for hit in scoped], ["qdrant-chunk-b"])

    def test_as_of_hides_a_chunk_disclosed_later(self) -> None:
        index = self._index(f"contract_{uuid4().hex}")
        index_version = "test-index-v1"
        index.upsert(
            chunks=[
                IndexedChunk(
                    chunk_id="qdrant-late-disclosure",
                    document_version_id="version-late",
                    effective_date="2025-12-31",
                    published_at="2026-04-15",
                    char_start=0,
                    char_end=10,
                    vector=[1.0, 0.0, 0.0, 0.0],
                    entity_id="alpha",
                )
            ],
            model="test-model",
            chunker_version="v1",
            index_version=index_version,
        )

        # The period ended 2025-12-31 but the filing was not public until
        # 2026-04-15. Filtering on the period end is the lookahead bias R112
        # removed from the relational path; the vector path must agree.
        early = index.query(
            vector=[1.0, 0.0, 0.0, 0.0],
            as_of="2026-02-01",
            index_version=index_version,
            limit=5,
        )
        self.assertEqual(early, [])

        late = index.query(
            vector=[1.0, 0.0, 0.0, 0.0],
            as_of="2026-05-01",
            index_version=index_version,
            limit=5,
        )
        self.assertEqual([hit.chunk_id for hit in late], ["qdrant-late-disclosure"])

    def test_query_requires_an_index_version(self) -> None:
        index = self._index(f"contract_{uuid4().hex}")

        with self.assertRaises(ValueError):
            index.query(vector=[1.0, 0.0], as_of="2025-12-31", index_version=None, limit=1)


if __name__ == "__main__":
    unittest.main()
