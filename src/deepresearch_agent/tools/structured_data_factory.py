from __future__ import annotations

import os
from collections.abc import Mapping

from deepresearch_agent.tools.akshare_structured_data import AKShareStructuredDataProvider
from deepresearch_agent.tools.fixture_structured_data import FixtureStructuredDataProvider
from deepresearch_agent.tools.provider import StructuredDataProvider

FIXTURE_STRUCTURED_PROVIDER_NAMES = {"", "fixture", "local", "deterministic"}
LIVE_STRUCTURED_PROVIDER_NAMES = {"akshare", "live"}


def build_structured_data_provider(environ: Mapping[str, str] | None = None) -> StructuredDataProvider:
    env = os.environ if environ is None else environ
    provider_name = env.get("DEEPRESEARCH_STRUCTURED_DATA_PROVIDER", "fixture").strip().lower()

    if provider_name in FIXTURE_STRUCTURED_PROVIDER_NAMES:
        return FixtureStructuredDataProvider()
    if provider_name in LIVE_STRUCTURED_PROVIDER_NAMES:
        return AKShareStructuredDataProvider()

    supported = ", ".join(sorted((FIXTURE_STRUCTURED_PROVIDER_NAMES - {""}) | LIVE_STRUCTURED_PROVIDER_NAMES))
    raise ValueError(
        f"Unsupported structured data provider '{provider_name}'. Supported providers: {supported}"
    )
