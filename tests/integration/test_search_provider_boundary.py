from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import FixtureSearchTool
from deepresearch_agent.workflow import DeepResearchEngine


class FakeSearchProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        self.calls.append((query, top_k, source_type))
        return [
            Source(
                id=f"fake-{len(self.calls)}",
                title=f"Fake source for {source_type or 'general'}",
                url=f"https://example.test/source/{len(self.calls)}",
                source_type=source_type or "official",
                published_at=date(2026, 1, 15),
                credibility=0.9,
                content=(
                    "AI agent adoption reached 42% in controlled finance workflows. "
                    "However risk and compliance constraints require citation checks and human oversight. "
                    "Evaluation should track citation accuracy, cost, latency, and token usage."
                ),
            )
        ][:top_k]


class SearchProviderBoundaryTests(unittest.TestCase):
    def test_engine_accepts_non_fixture_search_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            provider = FakeSearchProvider()
            engine = DeepResearchEngine(
                settings=settings,
                store=SQLiteStore(settings.storage_path),
                search_tool=provider,
            )
            state = engine.run(topic="provider boundary smoke", depth_level=1)

        self.assertNotIsInstance(engine.search_tool, FixtureSearchTool)
        self.assertGreater(len(provider.calls), 0)
        self.assertEqual(state.status, "done")
        self.assertGreater(len(state.evidence_store), 0)
        self.assertTrue(all(item.source_url.startswith("https://example.test/") for item in state.evidence_store))


if __name__ == "__main__":
    unittest.main()
