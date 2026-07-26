from __future__ import annotations

import json
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import Field

from deepresearch_agent.schemas import AgentDecision, StrictModel, utc_now
from deepresearch_agent.security import redact


class LLMCallTrace(StrictModel):
    role: str
    prompt: list[dict[str, str]]
    response: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_seconds: float = Field(ge=0)
    model: str
    cost_usd: float = Field(default=0.0, ge=0)
    cost_cny: float = Field(default=0.0, ge=0)
    price_source: str | None = None
    cache_hit: bool | None = None
    attempt: int = Field(ge=1)
    repair: bool = False
    error: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    recorded_at: datetime | None = None
    normalized_key: str | None = None


class ToolCallTrace(StrictModel):
    tool_spec: dict[str, Any]
    inputs: dict[str, Any]
    result: Any = None
    error: dict[str, Any] | None = None
    attempts: int = Field(ge=0)
    transport: Literal["local", "mcp"] = "local"
    server: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    recorded_at: datetime | None = None


class NodeTransitionTrace(StrictModel):
    node: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    sequence: int | None = Field(default=None, ge=1)
    recorded_at: datetime | None = None


class SignalReadTrace(StrictModel):
    """Reserved 017 slot for Reflector trajectory-signal reads."""

    signal_type: str
    source: str
    keys: tuple[str, ...] = ()


class MemoryWriteTrace(StrictModel):
    """Reserved 017 slot for cross-run procedural-memory writes."""

    memory_type: str
    lifecycle: str
    key: dict[str, Any]
    value_summary: dict[str, Any]


class AgentTrajectory(StrictModel):
    schema_version: int = 3
    run_id: str
    recorded_at: datetime = Field(default_factory=utc_now)
    request: dict[str, Any]
    llm_calls: list[LLMCallTrace] = Field(default_factory=list)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    node_transitions: list[NodeTransitionTrace] = Field(default_factory=list)
    agent_decisions: list[AgentDecision] = Field(default_factory=list)
    signal_reads: list[SignalReadTrace] = Field(default_factory=list)
    memory_writes: list[MemoryWriteTrace] = Field(default_factory=list)
    run_manifest_ref: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


class ReplayResult(StrictModel):
    mode: Literal["strict"]
    status: Literal["reproduced", "cache_miss", "mismatch"]
    cache_miss: str | None = None
    artifact_matches: dict[str, bool] = Field(default_factory=dict)


class TrajectoryRecorder:
    def __init__(self, *, run_id: str, request: dict[str, Any]) -> None:
        self.trajectory = AgentTrajectory(run_id=run_id, request=request)
        self._sequence = 0

    def _next_trace_fields(self) -> dict[str, Any]:
        existing = [
            item.sequence
            for item in (
                *self.trajectory.llm_calls,
                *self.trajectory.tool_calls,
                *self.trajectory.node_transitions,
            )
            if item.sequence is not None
        ]
        self._sequence = max([self._sequence, *existing], default=0) + 1
        return {"sequence": self._sequence, "recorded_at": utc_now()}

    def record_llm_call(self, call: LLMCallTrace) -> None:
        payload = call.model_dump()
        payload.update(self._next_trace_fields())
        payload["normalized_key"] = normalized_llm_key(
            role=call.role, prompt=call.prompt
        )
        call = LLMCallTrace.model_validate(payload)
        self.trajectory.llm_calls.append(call)

    def record_tool_call(self, call: ToolCallTrace) -> None:
        payload = call.model_dump()
        payload.update(self._next_trace_fields())
        call = ToolCallTrace.model_validate(payload)
        self.trajectory.tool_calls.append(call)

    def record_node_transition(self, transition: NodeTransitionTrace) -> None:
        payload = transition.model_dump()
        payload.update(self._next_trace_fields())
        transition = NodeTransitionTrace.model_validate(payload)
        self.trajectory.node_transitions.append(transition)

    def record_decision(self, decision: AgentDecision) -> None:
        self.trajectory.agent_decisions.append(decision)

    def record_signal_read(self, signal: SignalReadTrace) -> None:
        self.trajectory.signal_reads.append(signal)

    def record_memory_write(self, write: MemoryWriteTrace) -> None:
        self.trajectory.memory_writes.append(write)

    def finalize(
        self,
        *,
        manifest_ref: str | None,
        artifacts: dict[str, str],
    ) -> None:
        self.trajectory.run_manifest_ref = manifest_ref
        self.trajectory.artifacts = dict(sorted(artifacts.items()))

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            self.trajectory.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        path.write_text(redact(encoded) + "\n", encoding="utf-8")
        return path


_ACTIVE_RECORDER: ContextVar[TrajectoryRecorder | None] = ContextVar(
    "deepresearch_trajectory_recorder",
    default=None,
)


@contextmanager
def trajectory_recording(
    recorder: TrajectoryRecorder | None,
) -> Iterator[None]:
    token = _ACTIVE_RECORDER.set(recorder)
    try:
        yield
    finally:
        _ACTIVE_RECORDER.reset(token)


def active_trajectory_recorder() -> TrajectoryRecorder | None:
    return _ACTIVE_RECORDER.get()


def normalized_llm_key(*, role: str, prompt: list[dict[str, str]]) -> str:
    """Stable exact cache key; it deliberately has no fuzzy matching mode."""
    payload = json.dumps(
        {"role": role, "prompt": prompt},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_strict_replay_trajectory(trajectory: AgentTrajectory) -> None:
    """Reject incomplete or internally inconsistent strict-replay input."""
    if trajectory.schema_version != 3:
        raise ValueError(
            "trajectory schema_version mismatch: expected 3, "
            f"actual {trajectory.schema_version}"
        )
    missing = [
        key for key in ("topic", "mode", "depth_level", "recorded_plan")
        if key not in trajectory.request
    ]
    if missing:
        raise ValueError("trajectory request missing required field(s): " + ", ".join(missing))
    if not trajectory.artifacts:
        raise ValueError("trajectory artifacts missing: expected final artifact(s)")
    traces = [
        *trajectory.llm_calls,
        *trajectory.tool_calls,
        *trajectory.node_transitions,
    ]
    missing_fields: list[str] = []
    sequences: list[int] = []
    for trace in traces:
        name = type(trace).__name__
        if trace.sequence is None:
            missing_fields.append(f"{name}.sequence")
        else:
            sequences.append(trace.sequence)
        if trace.recorded_at is None:
            missing_fields.append(f"{name}.recorded_at")
    if missing_fields:
        raise ValueError("trajectory trace missing required field(s): " + ", ".join(missing_fields))
    if (
        len(sequences) != len(set(sequences))
        or sorted(sequences) != list(range(1, len(sequences) + 1))
    ):
        raise ValueError("trajectory trace sequence mismatch: expected contiguous FIFO order")
    for call in trajectory.llm_calls:
        expected = normalized_llm_key(role=call.role, prompt=call.prompt)
        if call.normalized_key != expected:
            raise ValueError(
                "trajectory LLM normalized_key mismatch: expected exact prompt key "
                f"for role {call.role}"
            )


def load_trajectory(path: Path) -> AgentTrajectory:
    return AgentTrajectory.model_validate_json(path.read_text(encoding="utf-8"))
