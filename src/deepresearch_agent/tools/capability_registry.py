from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from deepresearch_agent.schemas import StrictModel
from deepresearch_agent.tools.contract_adapter import (
    FETCH_TOOL_SPEC,
    SEARCH_TOOL_SPEC,
)
from deepresearch_agent.tools.contracts import ToolSpec
from deepresearch_agent.tools.disclosure_source import DISCLOSURE_TOOL_SPEC
from deepresearch_agent.tools.structured_trace import (
    STRUCTURED_DATA_TOOL_SPEC,
)

CapabilityCostLevel = Literal["free", "low", "medium", "high"]


class CapabilityMetadata(StrictModel):
    name: str
    applicable_subquestion_types: tuple[str, ...] = Field(min_length=1)
    cost_level: CapabilityCostLevel
    has_side_effect: bool
    tool_spec: ToolSpec

    @model_validator(mode="after")
    def _matches_tool_spec(self) -> "CapabilityMetadata":
        if self.name != self.tool_spec.name:
            raise ValueError("Capability name must match ToolSpec name")
        if self.cost_level != self.tool_spec.cost_class:
            raise ValueError("Capability cost level must match ToolSpec cost class")
        if self.has_side_effect != self.tool_spec.has_side_effect:
            raise ValueError(
                "Capability side-effect marker must match ToolSpec"
            )
        return self


class CapabilityRegistry:
    """Deterministic capability catalog; selection policy belongs to 016."""

    def __init__(self) -> None:
        self._metadata: dict[str, CapabilityMetadata] = {}
        self._implementations: dict[str, Any] = {}

    def register(
        self,
        metadata: CapabilityMetadata,
        implementation: Any,
    ) -> None:
        if metadata.name in self._metadata:
            raise ValueError(
                f"Capability already registered: {metadata.name}"
            )
        self._metadata[metadata.name] = metadata
        self._implementations[metadata.name] = implementation

    def get(self, name: str) -> CapabilityMetadata:
        try:
            return self._metadata[name]
        except KeyError as exc:
            raise KeyError(f"Unknown capability: {name}") from exc

    def resolve(self, name: str) -> Any:
        self.get(name)
        return self._implementations[name]

    def query(
        self,
        *,
        subquestion_type: str | None = None,
    ) -> list[CapabilityMetadata]:
        capabilities = sorted(
            self._metadata.values(),
            key=lambda item: item.name,
        )
        if subquestion_type is None:
            return capabilities
        return [
            item
            for item in capabilities
            if "*" in item.applicable_subquestion_types
            or subquestion_type in item.applicable_subquestion_types
        ]


def build_capability_registry(
    *,
    search_provider: Any,
    structured_data_provider: Any,
    disclosure_source: Any | None = None,
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityMetadata(
            name="web_search",
            applicable_subquestion_types=("*",),
            cost_level="low",
            has_side_effect=False,
            tool_spec=SEARCH_TOOL_SPEC,
        ),
        search_provider,
    )
    registry.register(
        CapabilityMetadata(
            name="web_fetch",
            applicable_subquestion_types=(
                "event",
                "financial_metric",
                "verify",
            ),
            cost_level="low",
            has_side_effect=False,
            tool_spec=FETCH_TOOL_SPEC,
        ),
        search_provider,
    )
    registry.register(
        CapabilityMetadata(
            name="structured_data_provider",
            applicable_subquestion_types=(
                "financial_metric",
                "market_price",
            ),
            cost_level="free",
            has_side_effect=False,
            tool_spec=STRUCTURED_DATA_TOOL_SPEC,
        ),
        structured_data_provider,
    )
    if disclosure_source is not None:
        registry.register(
            CapabilityMetadata(
                name="disclosure_source",
                applicable_subquestion_types=("financial_metric", "event"),
                cost_level="free",
                has_side_effect=False,
                tool_spec=DISCLOSURE_TOOL_SPEC,
            ),
            disclosure_source,
        )
    return registry
