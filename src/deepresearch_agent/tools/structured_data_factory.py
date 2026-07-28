from __future__ import annotations

import os
from collections.abc import Mapping

from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.tools.akshare_structured_data import AKShareStructuredDataProvider
from deepresearch_agent.tools.fixture_structured_data import FixtureStructuredDataProvider
from deepresearch_agent.tools.provider import StructuredDataProvider

FIXTURE_STRUCTURED_PROVIDER_NAMES = {"", "fixture", "local", "deterministic"}
LIVE_STRUCTURED_PROVIDER_NAMES = {"akshare", "live"}


class OptionalProviderDependencyError(RuntimeError):
    """A selected optional provider is unavailable in this installation."""


def build_structured_data_provider(
    environ: Mapping[str, str] | None = None,
    *,
    domain_pack: DomainPack | None = None,
) -> StructuredDataProvider:
    env = os.environ if environ is None else environ
    provider_name = env.get("DEEPRESEARCH_STRUCTURED_DATA_PROVIDER", "fixture").strip().lower()

    if provider_name in FIXTURE_STRUCTURED_PROVIDER_NAMES:
        return FixtureStructuredDataProvider(domain_pack=domain_pack)
    if provider_name in LIVE_STRUCTURED_PROVIDER_NAMES:
        try:
            return AKShareStructuredDataProvider(domain_pack=domain_pack)
        except ModuleNotFoundError as exc:
            if exc.name != "akshare":
                raise
            raise OptionalProviderDependencyError(
                "AKShare live provider requires the finance extra: "
                'pip install -e ".[finance]". For the offline fixture path, set '
                "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture."
            ) from exc

    supported = ", ".join(sorted((FIXTURE_STRUCTURED_PROVIDER_NAMES - {""}) | LIVE_STRUCTURED_PROVIDER_NAMES))
    raise ValueError(
        f"Unsupported structured data provider '{provider_name}'. Supported providers: {supported}"
    )
