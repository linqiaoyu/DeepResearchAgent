from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.tools.provider import SearchProvider
from deepresearch_agent.tools.recording_search import RecordingSearchProvider
from deepresearch_agent.tools.tavily_search import TavilySearchProvider

FIXTURE_PROVIDER_NAMES = {"", "fixture", "local", "deterministic"}
REAL_PROVIDER_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "serper": "SERPER_API_KEY",
}


@dataclass(frozen=True)
class ConfiguredSearchProvider:
    """Opt-in provider placeholder for providers without an adapter yet.

    This object records provider selection without performing live network calls
    until an adapter has mocked HTTP tests.
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
    recording_mode = env.get("DEEPRESEARCH_SEARCH_RECORDING_MODE", "live").strip().lower()
    recording_dir = env.get("DEEPRESEARCH_SEARCH_RECORDING_DIR", "").strip()

    if provider_name in FIXTURE_PROVIDER_NAMES:
        return FixtureSearchTool()

    if recording_mode == "replay":
        return RecordingSearchProvider(
            mode="replay",
            recording_dir=None if not recording_dir else Path(recording_dir),
        )

    key_name = REAL_PROVIDER_KEYS.get(provider_name)
    if key_name is None:
        supported_names = (FIXTURE_PROVIDER_NAMES - {""}) | set(REAL_PROVIDER_KEYS)
        supported = ", ".join(sorted(supported_names))
        raise ValueError(f"Unsupported search provider '{provider_name}'. Supported providers: {supported}")

    api_key = env.get(key_name, "").strip()
    if not api_key:
        if recording_mode == "record":
            raise ValueError(f"{provider_name} record mode requires {key_name}.")
        return FixtureSearchTool()

    if provider_name == "tavily":
        tavily = TavilySearchProvider(
            api_key=api_key,
            search_depth=env.get("DEEPRESEARCH_TAVILY_SEARCH_DEPTH", "basic").strip().lower(),
            include_raw_content=env.get("DEEPRESEARCH_TAVILY_INCLUDE_RAW_CONTENT", "").lower()
            in {"1", "true", "yes"},
        )
        if recording_mode == "record":
            return RecordingSearchProvider(
                mode="record",
                live_provider=tavily,
                recording_dir=None if not recording_dir else Path(recording_dir),
            )
        return tavily

    return ConfiguredSearchProvider(provider_name=provider_name, api_key=api_key)
