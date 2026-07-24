from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from deepresearch_agent.schemas import StrictModel


class ToolErrorKind(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    PERMANENT = "permanent"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


class RetryPolicy(StrictModel):
    retryable: bool
    base_backoff_s: float = Field(ge=0)
    max_attempts: int = Field(ge=1)


ERROR_RETRY_POLICIES: dict[ToolErrorKind, RetryPolicy] = {
    ToolErrorKind.TRANSIENT: RetryPolicy(retryable=True, base_backoff_s=0.5, max_attempts=3),
    ToolErrorKind.RATE_LIMITED: RetryPolicy(retryable=True, base_backoff_s=2.0, max_attempts=3),
    ToolErrorKind.AUTH: RetryPolicy(retryable=False, base_backoff_s=0.0, max_attempts=1),
    ToolErrorKind.NOT_FOUND: RetryPolicy(retryable=False, base_backoff_s=0.0, max_attempts=1),
    ToolErrorKind.PERMANENT: RetryPolicy(retryable=False, base_backoff_s=0.0, max_attempts=1),
    ToolErrorKind.TIMEOUT: RetryPolicy(retryable=True, base_backoff_s=1.0, max_attempts=3),
    ToolErrorKind.BUDGET_EXCEEDED: RetryPolicy(
        retryable=False,
        base_backoff_s=0.0,
        max_attempts=1,
    ),
}


class ToolSpec(StrictModel):
    name: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_s: float = Field(gt=0)
    retry_policy: dict[ToolErrorKind, RetryPolicy] = Field(
        default_factory=lambda: dict(ERROR_RETRY_POLICIES)
    )
    cost_class: Literal["free", "low", "medium", "high"]
    idempotent: bool
    has_side_effect: bool


class ToolError(StrictModel):
    kind: ToolErrorKind
    message: str
    exception_type: str | None = None


class ToolResult(StrictModel):
    ok: bool
    value: Any = None
    error: ToolError | None = None
    attempts: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    degraded: bool = False


class DegradationEvent(StrictModel):
    tool: str
    reason: ToolErrorKind
    impact: str
    attempts: int = Field(ge=0)
