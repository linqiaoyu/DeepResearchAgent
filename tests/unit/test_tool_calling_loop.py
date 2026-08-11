from __future__ import annotations

import unittest

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
    implementation: object,
    *,
    cost: str = "free",
    side_effect: bool = False,
) -> None:
    spec = ToolSpec(
        name=name,
        version="1",
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


class ToolCallingLoopTests(unittest.TestCase):
    def test_two_sequential_calls_receive_observations(self) -> None:
        registry = CapabilityRegistry()
        seen: list[int] = []
        _register(registry, "echo", lambda args: seen.append(args["value"]) or args)
        proposer = RecordedToolIntentProposer(
            [
                [ToolCallIntent(call_id="one", name="echo", arguments={"value": 1})],
                [ToolCallIntent(call_id="two", name="echo", arguments={"value": 2})],
                [],
            ]
        )

        result = ToolCallingLoop(registry, proposer).run(
            [{"role": "user", "content": "twice"}]
        )

        self.assertEqual(seen, [1, 2])
        self.assertEqual(result.executed_calls, 2)
        self.assertEqual([item.status for item in result.observations], ["succeeded", "succeeded"])
        self.assertEqual(result.termination, "completed")

    def test_unknown_paid_and_side_effect_intents_never_execute(self) -> None:
        registry = CapabilityRegistry()
        calls = {"paid": 0, "write": 0}
        _register(
            registry,
            "paid",
            lambda _args: calls.__setitem__("paid", calls["paid"] + 1),
            cost="low",
        )
        _register(
            registry,
            "write",
            lambda _args: calls.__setitem__("write", calls["write"] + 1),
            side_effect=True,
        )
        proposer = RecordedToolIntentProposer(
            [[
                ToolCallIntent(call_id="u", name="unknown"),
                ToolCallIntent(call_id="p", name="paid"),
                ToolCallIntent(call_id="s", name="write"),
            ], []]
        )

        result = ToolCallingLoop(registry, proposer).run([])

        self.assertEqual(calls, {"paid": 0, "write": 0})
        self.assertEqual(result.executed_calls, 0)
        self.assertEqual(
            [item.reason for item in result.observations],
            ["unknown_tool", "paid_call_not_authorized", "side_effect_not_authorized"],
        )

    def test_round_call_and_cost_limits_each_stop_execution(self) -> None:
        registry = CapabilityRegistry()
        _register(registry, "free", lambda args: args)
        _register(registry, "paid", lambda args: args, cost="low")
        repeated = [ToolCallIntent(call_id="one", name="free")]
        rounds = ToolCallingLoop(
            registry,
            RecordedToolIntentProposer([repeated, repeated, repeated]),
            limits=ToolLoopLimits(max_rounds=2),
        ).run([])
        calls = ToolCallingLoop(
            registry,
            RecordedToolIntentProposer([[
                ToolCallIntent(call_id="one", name="free"),
                ToolCallIntent(call_id="two", name="free"),
            ]]),
            limits=ToolLoopLimits(max_calls=1),
        ).run([])
        cost = ToolCallingLoop(
            registry,
            RecordedToolIntentProposer([[
                ToolCallIntent(call_id="paid", name="paid"),
            ]]),
            limits=ToolLoopLimits(max_cost_cny=0.5),
            policy=ToolAuthorizationPolicy(allow_paid=True),
            cost_estimator=lambda _level, _arguments: 1.0,
        ).run([])

        self.assertEqual(rounds.termination, "max_rounds")
        self.assertEqual(calls.termination, "max_calls")
        self.assertEqual(calls.executed_calls, 1)
        self.assertEqual(cost.termination, "max_cost")
        self.assertEqual(cost.executed_calls, 0)

    def test_recorded_proposals_replay_byte_identically(self) -> None:
        registry = CapabilityRegistry()
        _register(registry, "echo", lambda args: {"seen": args["value"]})
        batches = [
            [ToolCallIntent(call_id="one", name="echo", arguments={"value": 1})],
            [ToolCallIntent(call_id="two", name="echo", arguments={"value": 2})],
            [],
        ]

        first = ToolCallingLoop(registry, RecordedToolIntentProposer(batches)).run([])
        replay = ToolCallingLoop(registry, RecordedToolIntentProposer(batches)).run([])

        self.assertEqual(first.model_dump_json(), replay.model_dump_json())


if __name__ == "__main__":
    unittest.main()
