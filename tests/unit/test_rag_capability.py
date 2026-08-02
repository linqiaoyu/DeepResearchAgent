from __future__ import annotations

import unittest
from pathlib import Path

from deepresearch_agent.schemas import ResearchState, SubQuestion
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import DeterministicCapabilitySelector
from deepresearch_agent.tools.capability_registry import build_capability_registry
from deepresearch_agent.tools.reliable_execution import RunToolContext
from deepresearch_agent.workflow import DeepResearchEngine


class RagCapabilityTests(unittest.TestCase):
    def test_rag_capability_is_conditional_and_empty_index_never_fabricates_hits(self) -> None:
        disabled = DeepResearchEngine(Settings(storage_path=Path("artifacts/rag-disabled.db")))
        self.assertNotIn("rag_search", [item.name for item in disabled.capability_registry.query()])
        enabled = DeepResearchEngine(
            Settings(storage_path=Path("artifacts/rag-enabled.db"), rag_enabled=True, injection_guard_enabled=True)
        )
        context = RunToolContext.for_run()
        result = enabled.capability_registry.resolve("rag_search").search(
            query="q", as_of="2026-01-01", context=context
        )
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["trace"]["status"], "empty_index")
        self.assertEqual(context.degradation_events[-1].tool, "rag_search")
        self.assertEqual(context.degradation_events[-1].impact, "empty_result")
        disabled.close()
        enabled.close()

    def test_enabled_rag_uses_the_explicitly_injected_backend(self) -> None:
        class InjectedRag:
            fidelity = "real"

            def search(
                self, *, query: str, as_of: str, context: object | None = None
            ) -> dict[str, object]:
                del context
                return {"candidates": [{"chunk_id": "authoritative"}], "trace": {"query": query, "as_of": as_of}}

        engine = DeepResearchEngine(
            Settings(storage_path=Path("artifacts/rag-injected.db"), rag_enabled=True, injection_guard_enabled=True),
            rag_search=InjectedRag(),
        )
        result = engine.capability_registry.resolve("rag_search").search(query="q", as_of="2026-01-01")
        self.assertEqual(result["candidates"], [{"chunk_id": "authoritative"}])
        engine.close()

    def test_rag_disabled_preserves_capability_selection_byte_for_byte(self) -> None:
        """RAG rules may exist globally, but must be inert when unregistered."""

        question = SubQuestion(id="narrative", question="行业竞争战略", search_queries=["竞争战略"])
        engines = [
            DeepResearchEngine(Settings(storage_path=Path("artifacts/rag-selection-baseline.db"))),
            DeepResearchEngine(
                Settings(
                    storage_path=Path("artifacts/rag-selection-disabled.db"),
                    rag_enabled=False,
                    injection_guard_enabled=False,
                )
            ),
        ]
        try:
            selections = [
                DeterministicCapabilitySelector(engine.capability_registry)
                .select(ResearchState(topic="baseline"), question)
                .model_dump(mode="json")
                for engine in engines
            ]
        finally:
            for engine in engines:
                engine.close()
        self.assertEqual(selections[1], selections[0])
        self.assertNotIn("rag_search", selections[1]["selected_capabilities"])

    def test_rag_registry_rejects_implementation_without_production_context(self) -> None:
        class LegacyRag:
            def search(self, *, query: str, as_of: str) -> dict[str, object]:
                return {"candidates": [], "trace": {}}

        with self.assertRaisesRegex(TypeError, "LegacyRag.*context"):
            build_capability_registry(
                search_provider=object(),
                structured_data_provider=object(),
                rag_search=LegacyRag(),
            )


if __name__ == "__main__":
    unittest.main()
