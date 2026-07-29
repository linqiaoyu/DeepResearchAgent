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

    def test_enabled_rag_uses_the_explicitly_injected_backend(self) -> None:
        class InjectedRag:
            fidelity = "real"

            def search(self, *, query: str, as_of: str) -> dict[str, object]:
                return {"candidates": [{"chunk_id": "authoritative"}], "trace": {"query": query, "as_of": as_of}}

        engine = DeepResearchEngine(
            Settings(storage_path=Path("artifacts/rag-injected.db"), rag_enabled=True, injection_guard_enabled=True),
            rag_search=InjectedRag(),
        )
        result = engine.capability_registry.resolve("rag_search").search(query="q", as_of="2026-01-01")
        self.assertEqual(result["candidates"], [{"chunk_id": "authoritative"}])
        engine.close()


if __name__ == "__main__":
    unittest.main()
