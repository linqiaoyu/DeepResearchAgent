from __future__ import annotations

import unittest

from deepresearch_agent.tools import (
    ConfiguredSearchProvider,
    FixtureSearchTool,
    TavilySearchProvider,
    build_search_provider,
)


class SearchFactoryTests(unittest.TestCase):
    def test_defaults_to_fixture_provider(self) -> None:
        provider = build_search_provider({})

        self.assertIsInstance(provider, FixtureSearchTool)

    def test_real_provider_without_key_falls_back_to_fixture(self) -> None:
        provider = build_search_provider({"DEEPRESEARCH_SEARCH_PROVIDER": "tavily"})

        self.assertIsInstance(provider, FixtureSearchTool)

    def test_serper_without_key_falls_back_to_fixture(self) -> None:
        provider = build_search_provider({"DEEPRESEARCH_SEARCH_PROVIDER": "serper"})

        self.assertIsInstance(provider, FixtureSearchTool)

    def test_tavily_with_key_builds_adapter(self) -> None:
        provider = build_search_provider(
            {
                "DEEPRESEARCH_SEARCH_PROVIDER": "tavily",
                "TAVILY_API_KEY": "test-key",
            }
        )

        self.assertIsInstance(provider, TavilySearchProvider)

    def test_serper_with_key_records_configuration_without_live_call(self) -> None:
        provider = build_search_provider(
            {
                "DEEPRESEARCH_SEARCH_PROVIDER": "serper",
                "SERPER_API_KEY": "test-key",
            }
        )

        self.assertIsInstance(provider, ConfiguredSearchProvider)
        self.assertEqual(provider.provider_name, "serper")
        with self.assertRaisesRegex(NotImplementedError, "live adapter is not implemented"):
            provider.search("AI agent search smoke")

    def test_unsupported_provider_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported search provider 'unknown'"):
            build_search_provider({"DEEPRESEARCH_SEARCH_PROVIDER": "unknown"})


if __name__ == "__main__":
    unittest.main()
