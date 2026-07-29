from __future__ import annotations

import os
import unittest

from deepresearch_agent.rag.qdrant_index import QdrantIndex


@unittest.skipUnless(
    os.getenv("DEEPRESEARCH_QDRANT_URL"),
    "DEEPRESEARCH_QDRANT_URL not set",
)
class QdrantIntegrationTests(unittest.TestCase):
    def test_configured_service_accepts_collection_read(self) -> None:
        index = QdrantIndex(
            url=os.environ["DEEPRESEARCH_QDRANT_URL"],
            api_key=os.getenv("DEEPRESEARCH_QDRANT_API_KEY", ""),
            collection=os.getenv("DEEPRESEARCH_QDRANT_COLLECTION", "deepresearch_evidence"),
        )

        self.assertIn(index.collection_status(), {"exists", "missing"})
