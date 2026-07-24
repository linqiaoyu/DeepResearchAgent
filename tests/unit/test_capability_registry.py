from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    FETCH_TOOL_SPEC,
    CapabilityMetadata,
    CapabilityRegistry,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    build_capability_registry,
)
from deepresearch_agent.workflow import DeepResearchEngine


class CapabilityRegistryTest(unittest.TestCase):
    def test_register_query_resolve_are_deterministic(self) -> None:
        search = FixtureSearchTool()
        registry = build_capability_registry(
            search_provider=search,
            structured_data_provider=FixtureStructuredDataProvider(),
        )

        self.assertEqual(
            [item.name for item in registry.query()],
            ["structured_data_provider", "web_fetch", "web_search"],
        )
        self.assertEqual(
            [
                item.name
                for item in registry.query(subquestion_type="verify")
            ],
            ["web_fetch", "web_search"],
        )
        self.assertIs(registry.resolve("web_fetch"), search)

    def test_duplicate_and_unknown_capabilities_fail_closed(self) -> None:
        registry = CapabilityRegistry()
        metadata = CapabilityMetadata(
            name="web_fetch",
            applicable_subquestion_types=("verify",),
            cost_level="low",
            has_side_effect=False,
            tool_spec=FETCH_TOOL_SPEC,
        )
        registry.register(metadata, object())

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(metadata, object())
        with self.assertRaisesRegex(KeyError, "Unknown capability"):
            registry.resolve("missing")

    def test_engine_nodes_receive_all_tools_from_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                )
            )
            try:
                registry = engine.capability_registry
                self.assertIs(
                    engine.researcher.search_tool,
                    registry.resolve("web_search"),
                )
                self.assertIs(
                    engine.researcher.fetch_tool,
                    registry.resolve("web_fetch"),
                )
                self.assertIs(
                    engine.researcher.structured_data_provider,
                    registry.resolve("structured_data_provider"),
                )
            finally:
                engine._checkpoint_conn.close()


if __name__ == "__main__":
    unittest.main()
