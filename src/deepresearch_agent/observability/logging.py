from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, TextIO

from deepresearch_agent.security import redact


_CORRELATION: ContextVar[dict[str, str]] = ContextVar("deepresearch_correlation", default={})


@contextmanager
def correlation_context(**values: str | None) -> Iterator[None]:
    merged = {**_CORRELATION.get(), **{key: value for key, value in values.items() if value}}
    token = _CORRELATION.set(merged)
    try:
        yield
    finally:
        _CORRELATION.reset(token)


def correlation_values() -> dict[str, str]:
    return dict(_CORRELATION.get())


class JsonLogger:
    def __init__(self, *, enabled: bool = False, stream: TextIO | None = None) -> None:
        self.enabled = enabled
        self.stream = stream or sys.stderr

    def event(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **correlation_values(),
            **fields,
        }
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        try:
            self.stream.write(redact(encoded) + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            return
