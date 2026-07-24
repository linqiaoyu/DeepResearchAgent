from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import LLMConfig, RoleModelConfig
from deepresearch_agent.reflection import (
    ReflectionLLMInsight,
    ReflectionReasoningRequest,
    Reflector,
)
from deepresearch_agent.trajectory import (
    AgentTrajectory,
    TrajectoryRecorder,
    trajectory_recording,
)


class StubLLMReflectionReasoner:
    """Hand-written, zero-network adapter for the 019-A recording audit."""

    def __init__(self, client: LLMClient, run_id: str) -> None:
        self.client = client
        self.run_id = run_id

    def reason(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionLLMInsight:
        result = self.client.complete(
            role="reflector",
            run_id=self.run_id,
            schema=ReflectionLLMInsight,
            messages=[
                {
                    "role": "user",
                    "content": request.model_dump_json(),
                }
            ],
        )
        if not isinstance(result.parsed, ReflectionLLMInsight):
            raise AssertionError("stub reflector did not return typed output")
        return result.parsed


class SpendingEligibilityAuditTests(unittest.TestCase):
    def test_reflector_llm_call_records_replayable_costed_trace(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": ReflectionLLMInsight(
                            status="recorded_placeholder",
                            provider="stub_provider",
                        ).model_dump_json()
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1_000,
                "completion_tokens": 500,
                "total_tokens": 1_500,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=zero-cost-stub-key\n",
                encoding="utf-8",
            )
            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                config=LLMConfig(
                    roles={
                        "reflector": RoleModelConfig(
                            model="openai/deepseek-v4-flash",
                            api_base="https://api.deepseek.com",
                        )
                    }
                ),
                completion_func=lambda **_: response,
                env_path=env_path,
            )
            recorder = TrajectoryRecorder(
                run_id="reflector-recording-audit",
                request={"topic": "019-A"},
            )
            reflector = Reflector(
                StubLLMReflectionReasoner(
                    client,
                    "reflector-recording-audit",
                )
            )
            trajectory = AgentTrajectory(
                run_id="reflector-recording-audit",
                request={"topic": "019-A"},
            )
            with trajectory_recording(recorder):
                reflector.reflect(trajectory, [])
            trace_path = recorder.write(root / "trajectory.json")
            payload = json.loads(trace_path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["llm_calls"]), 1)
        call = payload["llm_calls"][0]
        self.assertEqual(call["role"], "reflector")
        self.assertEqual(call["model"], "openai/deepseek-v4-flash")
        self.assertEqual(call["prompt_tokens"], 1_000)
        self.assertEqual(call["completion_tokens"], 500)
        self.assertEqual(call["response"], response["choices"][0]["message"]["content"])
        self.assertAlmostEqual(call["cost_cny"], 0.002)
        self.assertAlmostEqual(call["cost_usd"], 0.00028)
        self.assertGreaterEqual(call["latency_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
