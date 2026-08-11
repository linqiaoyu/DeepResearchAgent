"""Measure the bounded intent/authorization/observation Tool Calling loop."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from deepresearch_agent.tools import (
    CapabilityMetadata,
    CapabilityRegistry,
    RecordedToolIntentProposer,
    ToolAuthorizationPolicy,
    ToolCallIntent,
    ToolCallingLoop,
    ToolLoopLimits,
    ToolSpec,
)


def _register(
    registry: CapabilityRegistry,
    name: str,
    implementation: Any,
    *,
    cost: str = "free",
    side_effect: bool = False,
) -> None:
    spec = ToolSpec(
        name=name,
        version="probe-v1",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        timeout_s=1,
        total_timeout_s=2,
        cost_class=cost,
        idempotent=not side_effect,
        has_side_effect=side_effect,
    )
    registry.register(
        CapabilityMetadata(
            name=name,
            applicable_subquestion_types=("*",),
            cost_level=cost,
            has_side_effect=side_effect,
            tool_spec=spec,
        ),
        implementation,
    )


def measure() -> dict[str, int | float]:
    registry = CapabilityRegistry()
    executions = {"echo": 0, "paid": 0, "write": 0}

    def counted(name: str) -> Any:
        def call(arguments: dict[str, Any]) -> dict[str, Any]:
            executions[name] += 1
            return {"name": name, **arguments}

        return call

    _register(registry, "echo", counted("echo"))
    _register(registry, "paid", counted("paid"), cost="low")
    _register(registry, "write", counted("write"), side_effect=True)
    sequential_batches = [
        [ToolCallIntent(call_id="one", name="echo", arguments={"value": 1})],
        [ToolCallIntent(call_id="two", name="echo", arguments={"value": 2})],
        [],
    ]
    sequential = ToolCallingLoop(
        registry, RecordedToolIntentProposer(sequential_batches)
    ).run([])
    replay = ToolCallingLoop(
        registry, RecordedToolIntentProposer(sequential_batches)
    ).run([])
    rejected = ToolCallingLoop(
        registry,
        RecordedToolIntentProposer([[
            ToolCallIntent(call_id="unknown", name="missing"),
            ToolCallIntent(call_id="paid", name="paid"),
            ToolCallIntent(call_id="write", name="write"),
        ], []]),
    ).run([])
    repeated = [ToolCallIntent(call_id="repeat", name="echo")]
    round_limited = ToolCallingLoop(
        registry,
        RecordedToolIntentProposer([repeated, repeated, repeated]),
        limits=ToolLoopLimits(max_rounds=2),
    ).run([])
    call_limited = ToolCallingLoop(
        registry,
        RecordedToolIntentProposer([[
            ToolCallIntent(call_id="call-1", name="echo"),
            ToolCallIntent(call_id="call-2", name="echo"),
        ]]),
        limits=ToolLoopLimits(max_calls=1),
    ).run([])
    cost_limited = ToolCallingLoop(
        registry,
        RecordedToolIntentProposer([[
            ToolCallIntent(call_id="cost", name="paid"),
        ]]),
        limits=ToolLoopLimits(max_cost_cny=0.5),
        policy=ToolAuthorizationPolicy(allow_paid=True),
        cost_estimator=lambda _level, _arguments: 1.0,
    ).run([])
    reasons = {item.reason for item in rejected.observations}
    return {
        "sequential_tool_observations": len(sequential.observations),
        "unknown_tool_executions": 0 if "unknown_tool" in reasons else 1,
        "unauthorized_tool_executions": executions["paid"] + executions["write"],
        "hard_limits_triggered": len(
            {
                round_limited.termination,
                call_limited.termination,
                cost_limited.termination,
            }
            & {"max_rounds", "max_calls", "max_cost"}
        ),
        "recorded_replay_match": float(
            sequential.model_dump_json() == replay.model_dump_json()
        ),
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "sequential_tool_observations": 2,
        "unknown_tool_executions": 0,
        "unauthorized_tool_executions": 0,
        "hard_limits_triggered": 3,
        "recorded_replay_match": 1.0,
    }
    return [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("tool_calling_loop_self_test=FAIL production probe is dirty")
    cases = {
        "single_step": {**metrics, "sequential_tool_observations": 1},
        "unknown_executed": {**metrics, "unknown_tool_executions": 1},
        "unauthorized_executed": {**metrics, "unauthorized_tool_executions": 1},
        "missing_limit": {**metrics, "hard_limits_triggered": 2},
        "replay_drift": {**metrics, "recorded_replay_match": 0.0},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"tool_calling_loop_self_test=FAIL accepted {label}")
    print(f"tool_calling_loop_self_test=PASS cases={len(cases) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
