"""Tool contracts and providers, loaded on demand by public symbol."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "akshare_structured_data": ("AKShareStructuredDataError", "AKShareStructuredDataProvider"),
    "capability_registry": ("FETCH_TOOL_SPEC", "STRUCTURED_DATA_TOOL_SPEC", "CapabilityMetadata", "CapabilityRegistry", "build_capability_registry"),
    "capability_selector": ("DEFAULT_CAPABILITY_RULES", "FIXED_CAPABILITY_SET", "CapabilitySelection", "CapabilitySelector", "DeterministicCapabilitySelector", "LLMCapabilitySelector", "classify_subquestion"),
    "calling_loop": ("AuthorizedToolCall", "LLMToolIntentProposer", "RecordedToolIntentProposer", "ToolAuthorizationPolicy", "ToolCallIntent", "ToolCallingLoop", "ToolLoopLimits", "ToolLoopResult", "ToolObservation"),
    "contract_adapter": ("ContractSearchProvider",),
    "contracts": ("ERROR_RETRY_POLICIES", "CircuitBreakerPolicy", "DegradationEvent", "RetryPolicy", "ToolError", "ToolErrorKind", "ToolResult", "ToolSpec"),
    "fixture_search": ("FixtureSearchTool",),
    "fixture_structured_data": ("FixtureStructuredDataProvider",),
    "sec_companyfacts": ("SecCompanyFactsError", "SecCompanyFactsProvider", "StructuredDataUnsupportedMetric"),
    "provider": ("FetchProvider", "SearchProvider", "StructuredDataProvider"),
    "recording_search": ("RecordingSearchProvider", "normalize_query_key", "recording_corpus_fingerprint"),
    "reliable_execution": ("CircuitBreaker", "CircuitState", "ExternalRequestBudget", "ReliableToolExecutor", "RetryBudget", "RunToolContext", "ToolExecutionError"),
    "search_factory": ("ConfiguredSearchProvider", "build_search_provider"),
    "structured_data_factory": ("build_structured_data_provider",),
    "structured_trace": ("TrajectoryStructuredDataProvider",),
    "tavily_search": ("TavilySearchError", "TavilySearchProvider"),
    "disclosure_source": ("CninfoDisclosureSource", "DisclosureSourceError", "FixtureDisclosureSource"),
}

_SYMBOL_TO_MODULE = {
    symbol: module for module, symbols in _EXPORTS.items() for symbol in symbols
}

__all__ = list(_SYMBOL_TO_MODULE)


def __getattr__(name: str) -> object:
    """Resolve a provider only when a consumer asks for that public symbol."""
    module = _SYMBOL_TO_MODULE.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module}"), name)
