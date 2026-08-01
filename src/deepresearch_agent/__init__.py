"""DeepResearchAgent package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepresearch_agent.workflow.engine import DeepResearchEngine

__all__ = ["DeepResearchEngine"]


def __getattr__(name: str) -> object:
    """Load the workflow only for callers that request the engine facade.

    Most scripts import a narrow submodule such as ``schemas`` or ``rag``.
    Importing the complete workflow for those paths makes their startup depend
    on every optional integration and can make an otherwise local probe hang
    before it reaches its own bounded operation.
    """
    if name == "DeepResearchEngine":
        from deepresearch_agent.workflow.engine import DeepResearchEngine

        return DeepResearchEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
