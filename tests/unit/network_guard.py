"""Fail-closed unit-test egress guard, installed by ``tests.unit``."""

from __future__ import annotations

import socket
import unittest
import inspect
from collections.abc import Callable
from typing import Any

_ORIGINAL_CONNECT = socket.socket.connect
_ALLOW_ATTR = "_deepresearch_allow_network"


def allow_network(test: Callable[..., Any]) -> Callable[..., Any]:
    """Explicit opt-out for a unit test that deliberately requires egress."""
    setattr(test, _ALLOW_ATTR, True)
    return test


def install() -> None:
    if getattr(socket.socket.connect, "_deepresearch_guard", False):
        return

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        host = str(address[0]) if isinstance(address, tuple) else ""
        if host in {"127.0.0.1", "::1", "localhost"} or _current_test_allows_network():
            return _ORIGINAL_CONNECT(sock, address)
        raise AssertionError(
            "unit test attempted network egress; use @allow_network only for "
            "an explicitly reviewed real-call test"
        )

    setattr(guarded_connect, "_deepresearch_guard", True)
    socket.socket.connect = guarded_connect


def _current_test_allows_network() -> bool:
    for frame_info in inspect.stack()[2:]:
        candidate = frame_info.frame.f_locals.get("self")
        method_name = getattr(candidate, "_testMethodName", "")
        method = getattr(candidate, method_name, None)
        if getattr(method, _ALLOW_ATTR, False):
            return True
    return False


class NetworkGuardedTestCase(unittest.TestCase):
    """Base for guard self-tests; suite-wide installation occurs at import time."""
