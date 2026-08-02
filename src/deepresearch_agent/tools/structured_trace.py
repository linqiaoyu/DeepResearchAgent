from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from deepresearch_agent.schemas import (
    StructuredDataRecord,
    SymbolInfo,
)
from deepresearch_agent.tools.contracts import ToolSpec
from deepresearch_agent.tools.provider import StructuredDataProvider
from deepresearch_agent.tools.reliable_execution import RunToolContext
from deepresearch_agent.trajectory import (
    ToolCallTrace,
    active_trajectory_recorder,
)

STRUCTURED_DATA_TOOL_SPEC = ToolSpec(
    name="structured_data_provider",
    version="1.0.0",
    input_schema={
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {
                "enum": [
                    "symbol_resolve",
                    "financial_indicators",
                    "price_history",
                ]
            }
        },
    },
    output_schema={
        "oneOf": [
            {"$ref": "SymbolInfo"},
            {"type": "null"},
            {
                "type": "array",
                "items": {"$ref": "StructuredDataRecord"},
            },
        ]
    },
    timeout_s=60.0,
    cost_class="free",
    idempotent=True,
    has_side_effect=False,
)


class TrajectoryStructuredDataProvider:
    """Record structured-provider calls without changing provider semantics."""

    def __init__(self, provider: StructuredDataProvider) -> None:
        self.provider = provider

    @property
    def fidelity(self) -> str:
        return str(getattr(self.provider, "fidelity", "unknown"))

    @property
    def provider_identity(self) -> str:
        """Expose the wrapped provider rather than this recording decorator."""

        return type(self.provider).__name__

    def set_run_context(self, context: RunToolContext) -> None:
        """Forward workflow-scoped budget state to a real provider when used."""

        setter = getattr(self.provider, "set_run_context", None)
        if callable(setter):
            setter(context)

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        return self._call(
            {
                "operation": "symbol_resolve",
                "company_name": company_name,
            },
            lambda: self.provider.symbol_resolve(company_name),
        )

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        return self._call(
            {
                "operation": "financial_indicators",
                "symbol": symbol,
                "periods": periods,
                "metrics": metrics,
            },
            lambda: self.provider.financial_indicators(
                symbol,
                periods=periods,
                metrics=metrics,
            ),
        )

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        return self._call(
            {
                "operation": "price_history",
                "symbol": symbol,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            lambda: self.provider.price_history(
                symbol,
                start_date,
                end_date,
            ),
        )

    def _call(self, inputs: dict[str, Any], call: Callable[[], Any]):
        try:
            result = call()
        except Exception as exc:
            recorder = active_trajectory_recorder()
            if recorder:
                recorder.record_tool_call(
                    ToolCallTrace(
                        tool_spec=(
                            STRUCTURED_DATA_TOOL_SPEC.model_dump(
                                mode="json"
                            )
                        ),
                        inputs=inputs,
                        error={
                            "kind": type(exc).__name__,
                            "message": str(exc),
                        },
                        attempts=1,
                    )
                )
            raise
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(
                ToolCallTrace(
                    tool_spec=STRUCTURED_DATA_TOOL_SPEC.model_dump(
                        mode="json"
                    ),
                    inputs=inputs,
                    result=_json_value(result),
                    attempts=1,
                )
            )
        return result


def _json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
