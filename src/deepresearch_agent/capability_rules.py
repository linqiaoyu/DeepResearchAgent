"""Provider-neutral defaults for deterministic capability routing."""

DEFAULT_CAPABILITY_RULES: dict[str, tuple[str, ...]] = {
    "financial_metric": ("disclosure_source", "structured_data_provider", "web_fetch", "web_search", "rag_search"),
    "market_price": ("structured_data_provider", "web_search", "rag_search"),
    "verify": ("web_fetch", "web_search", "rag_search"),
    "event": ("disclosure_source", "web_fetch", "web_search", "rag_search"),
    "narrative": ("web_search", "rag_search"),
}
