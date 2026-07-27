"""Fail-closed unit-test egress guard, installed by ``tests.unit``."""

from __future__ import annotations

import socket
import unittest
from contextvars import ContextVar, copy_context
from collections.abc import Callable
from typing import Any

_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ALLOW_ATTR = "_deepresearch_allow_network"
_NETWORK_ALLOWED: ContextVar[bool] = ContextVar(
    "deepresearch_network_allowed",
    default=False,
)


def allow_network(test: Callable[..., Any]) -> Callable[..., Any]:
    """Explicit opt-out for a unit test that deliberately requires egress."""
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        token = _NETWORK_ALLOWED.set(True)
        try:
            return test(*args, **kwargs)
        finally:
            _NETWORK_ALLOWED.reset(token)

    setattr(wrapped, _ALLOW_ATTR, True)
    return wrapped


def run_with_network_context(target: Callable[..., Any]) -> Callable[..., Any]:
    """Capture the current explicit opt-out for a child worker thread."""
    context = copy_context()
    return lambda: context.run(target)


def install() -> None:
    if getattr(socket.socket.connect, "_deepresearch_guard", False):
        return

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        host = str(address[0]) if isinstance(address, tuple) else ""
        if host in {"127.0.0.1", "::1", "localhost"} or _current_test_allows_network():
            return _ORIGINAL_CONNECT(sock, address)
        raise AssertionError(
            "test attempted network egress; use @allow_network only for "
            "an explicitly reviewed real-call test"
        )

    setattr(guarded_connect, "_deepresearch_guard", True)
    socket.socket.connect = guarded_connect

    def guarded_connect_ex(sock: socket.socket, address: Any) -> int:
        host = str(address[0]) if isinstance(address, tuple) else ""
        if host in {"127.0.0.1", "::1", "localhost"} or _current_test_allows_network():
            return _ORIGINAL_CONNECT_EX(sock, address)
        raise AssertionError(
            "test attempted network egress; use @allow_network only for "
            "an explicitly reviewed real-call test"
        )

    setattr(guarded_connect_ex, "_deepresearch_guard", True)
    socket.socket.connect_ex = guarded_connect_ex


def _current_test_allows_network() -> bool:
    return _NETWORK_ALLOWED.get()


class NetworkGuardedTestCase(unittest.TestCase):
    """Base for guard self-tests; suite-wide installation occurs at import time."""
