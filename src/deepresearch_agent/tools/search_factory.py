from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.tools.provider import SearchProvider

FIXTURE_PROVIDER_NAMES = {"", "fixture", "local", "deterministic"}
REAL_PROVIDER_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "serper": "SERPER_API_KEY",
}


@dataclass(frozen=True)
class ConfiguredSearchProvider:
    """Opt-in real provider placeholder.

    This object records provider selection without performing live network calls.
    A future adapter should replace this class once mocked HTTP tests exist.
    """

    provider_name: str
    api_key: str

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        raise NotImplementedError(
            f"{self.provider_name} search is configured but the live adapter is not implemented yet. "
            "Unset DEEPRESEARCH_SEARCH_PROVIDER to use the deterministic fixture provider."
        )


def build_search_provider(environ: Mapping[str, str] | None = None) -> SearchProvider:
    env = os.environ if environ is None else environ
    provider_name = env.get("DEEPRESEARCH_SEARCH_PROVIDER", "fixture").strip().lower()

    if provider_name in FIXTURE_PROVIDER_NAMES:
        return FixtureSearchTool()

    key_name = REAL_PROVIDER_KEYS.get(provider_name)
    if key_name is None:
        supported_names = (FIXTURE_PROVIDER_NAMES - {""}) | set(REAL_PROVIDER_KEYS)
        supported = ", ".join(sorted(supported_names))
        raise ValueError(f"Unsupported search provider '{provider_name}'. Supported providers: {supported}")

    api_key = env.get(key_name, "").strip()
    if not api_key:
        return FixtureSearchTool()

    return ConfiguredSearchProvider(provider_name=provider_name, api_key=api_key)
