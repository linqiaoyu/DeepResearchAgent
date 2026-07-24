from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import (
    ToolCallTrace,
    TrajectoryRecorder,
    load_trajectory,
    trajectory_recording,
)
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


TOPICS = (
    "宁德时代 2024 年业绩与欧洲工厂扩张研究",
    "AI Agent 在财富管理行业的落地机会研究",
)


class TrajectoryReplayTests(unittest.TestCase):
    def test_strict_replay_reproduces_two_reports_byte_for_byte(self) -> None:
        for topic in TOPICS:
            with self.subTest(topic=topic), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                settings = replace(
                    Settings(
                        storage_path=root / "record.db",
                        runs_root=root / "runs",
                        as_of=date(2026, 7, 9),
                    ),
                    trajectory_record_enabled=True,
                    structured_logging_enabled=False,
                )
                engine = DeepResearchEngine(settings=settings)
                state = engine.run(topic=topic, depth_level=1)
                engine._checkpoint_conn.close()
                path = root / "runs" / state.research_id / "trajectory.json"

                trajectory = load_trajectory(path)
                result = replay_trajectory(trajectory, mode="strict")

                self.assertEqual(result.status, "reproduced")
                self.assertEqual(result.artifact_matches, {"report.md": True})
                self.assertGreater(len(trajectory.tool_calls), 0)
                self.assertGreater(len(trajectory.node_transitions), 0)
                self.assertEqual(trajectory.llm_calls, [])
                self.assertEqual(trajectory.agent_decisions, [])
                self.assertTrue(trajectory.run_manifest_ref)

    def test_strategy_cache_miss_stops_without_inventing_response(self) -> None:
        recorder = TrajectoryRecorder(
            run_id="synthetic",
            request={
                "topic": "synthetic",
                "depth_level": 1,
                "as_of": "2026-07-09",
                "mode": "deterministic",
            },
        )

        result = replay_trajectory(
            recorder.trajectory,
            mode="strategy",
            required_calls=["llm:critic"],
        )

        self.assertEqual(result.status, "cache_miss")
        self.assertEqual(result.cache_miss, "llm:critic")

    def test_sidecar_has_all_six_field_groups_and_redacts(self) -> None:
        recorder = TrajectoryRecorder(
            run_id="redact",
            request={"topic": "secret sk-abcdefghijklmnop"},
        )
        recorder.record_tool_call(
            ToolCallTrace(
                tool_spec={"name": "fixture"},
                inputs={"token": "sk-abcdefghijklmnop"},
                result={"ok": True},
                attempts=1,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = recorder.write(Path(tmp) / "trajectory.json")
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)

        self.assertNotIn("sk-abcdefghijklmnop", raw)
        self.assertIn("[REDACTED_API_KEY]", raw)
        for field in (
            "llm_calls",
            "tool_calls",
            "node_transitions",
            "agent_decisions",
            "run_manifest_ref",
            "artifacts",
        ):
            self.assertIn(field, payload)

    def test_llm_boundary_records_full_prompt_response_and_usage(self) -> None:
        response = {
            "choices": [{"message": {"content": "fixture response"}}],
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 2,
                "total_tokens": 6,
            },
        }
        recorder = TrajectoryRecorder(
            run_id="llm-synthetic",
            request={"topic": "synthetic"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=fixture-key\n", encoding="utf-8")
            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                completion_func=lambda **_: response,
                env_path=env_path,
            )
            with trajectory_recording(recorder):
                client.complete(
                    role="planner",
                    messages=[{"role": "user", "content": "full prompt"}],
                    run_id="llm-synthetic",
                )

        call = recorder.trajectory.llm_calls[0]
        self.assertEqual(call.prompt, [{"role": "user", "content": "full prompt"}])
        self.assertEqual(call.response, "fixture response")
        self.assertEqual(call.total_tokens, 6)
        self.assertEqual(call.model, "openai/deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
