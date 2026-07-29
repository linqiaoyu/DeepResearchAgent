"""Composition-root setup for the engine's bounded capability registry."""

from __future__ import annotations

from typing import Any

from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.observability import JsonLogger
from deepresearch_agent.rag.retrieval import EmptyRagSearchTool
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    CapabilityRegistry,
    SearchProvider,
    StructuredDataProvider,
    TrajectoryStructuredDataProvider,
    build_capability_registry,
    build_search_provider,
    build_structured_data_provider,
)
from deepresearch_agent.tools.contract_adapter import ContractSearchProvider
from deepresearch_agent.tools.disclosure_source import (
    CninfoDisclosureSource,
    FixtureDisclosureSource,
)


def build_engine_capability_registry(
    *,
    settings: Settings,
    domain_pack: DomainPack,
    logger: JsonLogger,
    search_tool: SearchProvider | None,
    structured_data_provider: StructuredDataProvider | None,
    disclosure_source: Any | None,
) -> CapabilityRegistry:
    configured_search_tool = search_tool or build_search_provider(as_of=settings.as_of)
    if settings.tool_contract_enabled:
        configured_search_tool = ContractSearchProvider(configured_search_tool, logger=logger)
    configured_structured_provider = TrajectoryStructuredDataProvider(
        structured_data_provider or build_structured_data_provider(domain_pack=domain_pack)
    )
    configured_disclosure_source = disclosure_source or (
        FixtureDisclosureSource(domain_pack=domain_pack)
        if settings.execution_mode == "deterministic"
        else CninfoDisclosureSource(
            pdf_max_pages=settings.pdf_max_pages,
            char_limit=settings.tavily_raw_content_char_limit,
            domain_pack=domain_pack,
        )
    )
    return build_capability_registry(
        search_provider=configured_search_tool,
        structured_data_provider=configured_structured_provider,
        disclosure_source=configured_disclosure_source,
        rag_search=EmptyRagSearchTool() if settings.rag_enabled else None,
    )
