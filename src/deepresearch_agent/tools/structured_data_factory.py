from __future__ import annotations

import os
from collections.abc import Mapping

from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.tools.akshare_structured_data import AKShareStructuredDataProvider
from deepresearch_agent.tools.composite_structured_data import build_composite
from deepresearch_agent.tools.fixture_structured_data import FixtureStructuredDataProvider
from deepresearch_agent.tools.provider import StructuredDataProvider
from deepresearch_agent.tools.sec_companyfacts import SecCompanyFactsProvider

FIXTURE_STRUCTURED_PROVIDER_NAMES = {"", "fixture", "local", "deterministic"}
LIVE_STRUCTURED_PROVIDER_NAMES = {"akshare", "live"}
SEC_STRUCTURED_PROVIDER_NAMES = {"sec", "sec_companyfacts", "sec-companyfacts"}
#: R101: every live run selected one data source before the question was known,
#: so a US-listed issuer was asked of an A-share source, `symbol_resolve` timed
#: out, and the report said no citable disclosure existed while the provider
#: holding the answer was never called. This name asks each provider in turn.
ROUTED_STRUCTURED_PROVIDER_NAMES = {"auto", "routed", "composite"}
#: SEC first because its miss is a lookup in a table it already holds, while an
#: AKShare miss costs a 15-second network timeout. Order changes what a miss
#: costs, not which provider ends up serving the request.
ROUTED_PROVIDER_ORDER = ("sec", "akshare")


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
        return _akshare(domain_pack)
    if provider_name in SEC_STRUCTURED_PROVIDER_NAMES:
        return SecCompanyFactsProvider(domain_pack=domain_pack)
    if provider_name in ROUTED_STRUCTURED_PROVIDER_NAMES:
        builders = {
            "sec": lambda: SecCompanyFactsProvider(domain_pack=domain_pack),
            "akshare": lambda: _akshare(domain_pack),
        }
        providers = []
        for name in ROUTED_PROVIDER_ORDER:
            try:
                providers.append((name, builders[name]()))
            except OptionalProviderDependencyError:
                # `auto` is a best-effort route. An unavailable optional
                # provider must not prevent the remaining providers from
                # answering the question; an explicit `akshare` selection
                # still raises the actionable dependency error above.
                continue
        return build_composite(providers)

    supported = ", ".join(
        sorted(
            (FIXTURE_STRUCTURED_PROVIDER_NAMES - {""})
            | LIVE_STRUCTURED_PROVIDER_NAMES
            | SEC_STRUCTURED_PROVIDER_NAMES
            | ROUTED_STRUCTURED_PROVIDER_NAMES
        )
    )
    raise ValueError(
        f"Unsupported structured data provider '{provider_name}'. Supported providers: {supported}"
    )


def _akshare(domain_pack: DomainPack | None) -> StructuredDataProvider:
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
