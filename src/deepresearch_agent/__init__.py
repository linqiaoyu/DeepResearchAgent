"""DeepResearchAgent package."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {"workflow.engine": ("DeepResearchEngine",)}
_SYMBOL_TO_MODULE = {symbol: module for module, symbols in _EXPORTS.items() for symbol in symbols}
__all__ = list(_SYMBOL_TO_MODULE)


def __getattr__(name: str) -> object:
    """Load the workflow only for callers that request the engine facade.

    Most scripts import a narrow submodule such as ``schemas`` or ``rag``.
    Importing the complete workflow for those paths makes their startup depend
    on every optional integration and can make an otherwise local probe hang
    before it reaches its own bounded operation.
    """
    module = _SYMBOL_TO_MODULE.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module}"), name)
