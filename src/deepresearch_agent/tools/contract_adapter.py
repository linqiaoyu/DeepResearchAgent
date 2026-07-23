from __future__ import annotations

from typing import Any

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools.contracts import ToolSpec
from deepresearch_agent.tools.provider import SearchProvider
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
)


SEARCH_TOOL_SPEC = ToolSpec(
    name="web_search",
    version="1.0.0",
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1},
            "source_type": {"type": ["string", "null"]},
        },
    },
    output_schema={"type": "array", "items": {"$ref": "Source"}},
    timeout_s=60.0,
    cost_class="low",
    idempotent=True,
    has_side_effect=False,
)


class ContractSearchProvider:
    """Opt-in adapter; the default factory path returns the original provider."""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        executor: ReliableToolExecutor | None = None,
        context: RunToolContext | None = None,
    ) -> None:
        self.provider = provider
        self.executor = executor or ReliableToolExecutor()
        self.context = context or RunToolContext(retry_budget=RetryBudget(max_retries=6))

    def search(
        self,
        query: str,
        top_k: int = 3,
        source_type: str | None = None,
    ) -> list[Source]:
        result = self.executor.execute(
            SEARCH_TOOL_SPEC,
            lambda: self.provider.search(query, top_k=top_k, source_type=source_type),
            self.context,
            degrade=True,
            degraded_value=[],
            impact="search results unavailable; downstream evidence coverage may decrease",
        )
        return list(result.value or [])

    def fetch(self, url: str) -> Source | None:
        fetch = getattr(self.provider, "fetch", None)
        if not callable(fetch):
            return None
        return fetch(url)

    @property
    def degradation_events(self) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self.context.degradation_events]
