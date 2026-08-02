"""Auditable retrieval primitives; candidates never become Evidence directly."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {"ingest": ("ingest_corpus",)}
_SYMBOL_TO_MODULE = {symbol: module for module, symbols in _EXPORTS.items() for symbol in symbols}
__all__ = list(_SYMBOL_TO_MODULE)


def __getattr__(name: str) -> object:
    """Avoid loading PDF ingestion for consumers of retrieval-only modules."""
    module = _SYMBOL_TO_MODULE.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module}"), name)
