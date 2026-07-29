from __future__ import annotations

import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class RagCapabilityTests(unittest.TestCase):
    def test_rag_capability_is_conditional_and_empty_index_never_fabricates_hits(self) -> None:
        disabled = DeepResearchEngine(Settings(storage_path=Path("artifacts/rag-disabled.db")))
        self.assertNotIn("rag_search", [item.name for item in disabled.capability_registry.query()])
        enabled = DeepResearchEngine(
            Settings(storage_path=Path("artifacts/rag-enabled.db"), rag_enabled=True, injection_guard_enabled=True)
        )
        result = enabled.capability_registry.resolve("rag_search").search(query="q", as_of="2026-01-01")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["trace"]["status"], "empty_index")
        disabled.close()
        enabled.close()


if __name__ == "__main__":
    unittest.main()
