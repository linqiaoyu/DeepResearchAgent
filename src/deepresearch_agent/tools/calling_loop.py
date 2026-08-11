"""Bounded model-intent -> Harness-authorization -> observation loop."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol

from pydantic import Field

from deepresearch_agent.schemas import StrictModel
from deepresearch_agent.tools.capability_registry import CapabilityRegistry
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RunToolContext,
)
from deepresearch_agent.trajectory import ToolCallTrace, active_trajectory_recorder


class ToolCallIntent(StrictModel):
    """A model suggestion. Construction grants no authority to execute it."""

    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class AuthorizedToolCall(StrictModel):
    call_id: str
    name: str
    arguments: dict[str, Any]
    cost_class: Literal["free", "low", "medium", "high"]
    estimated_cost_cny: float = Field(ge=0)
    has_side_effect: bool


class ToolObservation(StrictModel):
    call_id: str
    name: str
    status: Literal["succeeded", "degraded", "failed", "rejected"]
    value: Any = None
    error: str | None = None
    reason: str | None = None
    attempts: int = Field(default=0, ge=0)
    estimated_cost_cny: float = Field(default=0.0, ge=0)


class ToolLoopLimits(StrictModel):
    max_rounds: int = Field(default=4, ge=1)
    max_calls: int = Field(default=8, ge=1)
    max_cost_cny: float = Field(default=2.0, ge=0)


class ToolAuthorizationPolicy(StrictModel):
    allowed_tools: tuple[str, ...] | None = None
    allow_paid: bool = False
    allow_side_effects: bool = False


class ToolLoopResult(StrictModel):
    intents: list[ToolCallIntent] = Field(default_factory=list)
    authorized_calls: list[AuthorizedToolCall] = Field(default_factory=list)
    observations: list[ToolObservation] = Field(default_factory=list)
    rounds: int = Field(ge=0)
    executed_calls: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0)
    termination: Literal[
        "completed",
        "max_rounds",
        "max_calls",
        "max_cost",
    ]


class ToolIntentProposer(Protocol):
    def propose(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        round_number: int,
    ) -> Sequence[ToolCallIntent]: ...


class RecordedToolIntentProposer:
    """Exact ordered proposal batches for offline replay and tests."""

    def __init__(self, batches: Sequence[Sequence[ToolCallIntent]]) -> None:
        self._batches = tuple(tuple(batch) for batch in batches)

    def propose(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        round_number: int,
    ) -> Sequence[ToolCallIntent]:
        del messages, tools
        index = round_number - 1
        return self._batches[index] if index < len(self._batches) else ()


class LLMToolIntentProposer:
    """Adapt `LLMClient.complete_with_tools` without granting execution rights."""

    def __init__(self, llm_client: Any, *, role: str, run_id: str) -> None:
        self.llm_client = llm_client
        self.role = role
        self.run_id = run_id

    def propose(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        round_number: int,
    ) -> Sequence[ToolCallIntent]:
        result = self.llm_client.complete_with_tools(
            role=self.role,
            run_id=self.run_id,
            messages=messages,
            tools=tools,
        )
        intents: list[ToolCallIntent] = []
        for index, raw_call in enumerate(result.tool_calls):
            function = raw_call.get("function", {})
            if not isinstance(function, dict):
                function = {}
            raw_arguments = function.get("arguments", {})
            if isinstance(raw_arguments, str):
                try:
                    raw_arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    raw_arguments = {}
            arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
            intents.append(
                ToolCallIntent(
                    call_id=str(raw_call.get("id") or f"r{round_number}c{index + 1}"),
                    name=str(function.get("name", "<malformed_tool_call>")),
                    arguments=arguments,
                )
            )
        return intents


_DEFAULT_COST_CNY = {"free": 0.0, "low": 0.01, "medium": 0.1, "high": 1.0}


class ToolCallingLoop:
    def __init__(
        self,
        registry: CapabilityRegistry,
        proposer: ToolIntentProposer,
        *,
        limits: ToolLoopLimits | None = None,
        policy: ToolAuthorizationPolicy | None = None,
        executor: ReliableToolExecutor | None = None,
        context: RunToolContext | None = None,
        cost_estimator: Callable[[str, dict[str, Any]], float] | None = None,
        invoker: Callable[[Any, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.registry = registry
        self.proposer = proposer
        self.limits = limits or ToolLoopLimits()
        self.policy = policy or ToolAuthorizationPolicy()
        self.executor = executor or ReliableToolExecutor()
        self.context = context or RunToolContext.for_run()
        self.cost_estimator = cost_estimator or self._default_cost
        self.invoker = invoker or self._invoke

    def run(self, messages: Sequence[dict[str, str]]) -> ToolLoopResult:
        transcript = [dict(message) for message in messages]
        tools = [self._tool_schema(item.name) for item in self.registry.query()]
        intents: list[ToolCallIntent] = []
        authorized: list[AuthorizedToolCall] = []
        observations: list[ToolObservation] = []
        executed = 0
        cost = 0.0
        termination: Literal["completed", "max_rounds", "max_calls", "max_cost"] = (
            "completed"
        )
        rounds = 0
        for round_number in range(1, self.limits.max_rounds + 1):
            rounds = round_number
            proposed = list(
                self.proposer.propose(
                    messages=transcript,
                    tools=tools,
                    round_number=round_number,
                )
            )
            intents.extend(proposed)
            if not proposed:
                termination = "completed"
                break
            for intent in proposed:
                metadata = self._metadata_or_none(intent.name)
                rejection = self._rejection_reason(intent.name, metadata)
                if rejection is not None:
                    observation = ToolObservation(
                        call_id=intent.call_id,
                        name=intent.name,
                        status="rejected",
                        reason=rejection,
                    )
                    observations.append(observation)
                    self._append_observation(transcript, observation)
                    continue
                assert metadata is not None
                estimated = self.cost_estimator(metadata.cost_level, intent.arguments)
                if executed >= self.limits.max_calls:
                    termination = "max_calls"
                    break
                if cost + estimated > self.limits.max_cost_cny:
                    termination = "max_cost"
                    break
                call = AuthorizedToolCall(
                    call_id=intent.call_id,
                    name=intent.name,
                    arguments=dict(intent.arguments),
                    cost_class=metadata.cost_level,
                    estimated_cost_cny=estimated,
                    has_side_effect=metadata.has_side_effect,
                )
                authorized.append(call)
                implementation = self.registry.resolve(intent.name)
                result = self.executor.execute(
                    metadata.tool_spec,
                    lambda implementation=implementation, arguments=dict(intent.arguments): (
                        self.invoker(implementation, arguments)
                    ),
                    self.context,
                    degrade=True,
                    degraded_value=None,
                    impact="authorized tool call unavailable",
                )
                executed += 1
                cost += estimated
                observation = ToolObservation(
                    call_id=intent.call_id,
                    name=intent.name,
                    status=(
                        "succeeded"
                        if result.ok
                        else "degraded"
                        if result.degraded
                        else "failed"
                    ),
                    value=result.value,
                    error=result.error.message if result.error else None,
                    attempts=result.attempts,
                    estimated_cost_cny=estimated,
                )
                observations.append(observation)
                self._append_observation(transcript, observation)
                self._record_trace(metadata.tool_spec.model_dump(mode="json"), intent, observation)
            if termination in {"max_calls", "max_cost"}:
                break
        else:
            termination = "max_rounds"
        return ToolLoopResult(
            intents=intents,
            authorized_calls=authorized,
            observations=observations,
            rounds=rounds,
            executed_calls=executed,
            estimated_cost_cny=cost,
            termination=termination,
        )

    def _tool_schema(self, name: str) -> dict[str, Any]:
        spec = self.registry.get(name).tool_spec
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": f"cost={spec.cost_class}; side_effect={spec.has_side_effect}",
                "parameters": spec.input_schema,
            },
        }

    def _metadata_or_none(self, name: str) -> Any | None:
        try:
            return self.registry.get(name)
        except KeyError:
            return None

    def _rejection_reason(self, name: str, metadata: Any | None) -> str | None:
        if metadata is None:
            return "unknown_tool"
        if self.policy.allowed_tools is not None and name not in self.policy.allowed_tools:
            return "not_allowlisted"
        if metadata.has_side_effect and not self.policy.allow_side_effects:
            return "side_effect_not_authorized"
        if metadata.cost_level != "free" and not self.policy.allow_paid:
            return "paid_call_not_authorized"
        return None

    @staticmethod
    def _append_observation(
        transcript: list[dict[str, str]], observation: ToolObservation
    ) -> None:
        transcript.append(
            {
                "role": "tool",
                "content": observation.model_dump_json(),
            }
        )

    @staticmethod
    def _invoke(implementation: Any, arguments: dict[str, Any]) -> Any:
        call = getattr(implementation, "call", None)
        if callable(call):
            return call(arguments)
        if callable(implementation):
            return implementation(arguments)
        raise TypeError("registered tool implementation is not callable")

    @staticmethod
    def _default_cost(cost_level: str, _arguments: dict[str, Any]) -> float:
        return _DEFAULT_COST_CNY[cost_level]

    @staticmethod
    def _record_trace(
        tool_spec: dict[str, Any],
        intent: ToolCallIntent,
        observation: ToolObservation,
    ) -> None:
        recorder = active_trajectory_recorder()
        if recorder is None:
            return
        recorder.record_tool_call(
            ToolCallTrace(
                tool_spec=tool_spec,
                inputs=dict(intent.arguments),
                result=observation.value,
                error=(
                    {"kind": observation.status, "message": observation.error}
                    if observation.error
                    else None
                ),
                attempts=observation.attempts,
            )
        )
