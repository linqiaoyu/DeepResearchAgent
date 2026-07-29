from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.mcp import MCPStdioClient
from deepresearch_agent.schemas import (
    StructuredDataRecord,
    StructuredDataRequest,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    FixtureStructuredDataProvider,
    ReliableToolExecutor,
)
from deepresearch_agent.trajectory import (
    LLMCallTrace,
    MemoryWriteTrace,
    SignalReadTrace,
    ToolCallTrace,
    TrajectoryRecorder,
    TrajectoryTermination,
    load_trajectory,
    trajectory_recording,
    validate_strict_replay_trajectory,
)
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


class NumericRelationProvider(FixtureStructuredDataProvider):
    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        common = {
            "entity": "宁德时代",
            "symbol": symbol,
            "dimension": "全年",
            "data_source": "numeric-superset-fixture",
            "as_of": date(2026, 7, 9),
        }
        return [
            StructuredDataRecord(
                **common,
                metric_name="营业收入同比增长率",
                period="2024",
                value=99,
                unit="%",
            ),
            StructuredDataRecord(
                **common,
                metric_name="营业收入",
                period="2024",
                value=120,
                unit="亿元",
            ),
            StructuredDataRecord(
                **common,
                metric_name="营收",
                period="2023",
                value=100,
                unit="亿元",
            ),
        ]


class StructuredPlanner:
    def __init__(self, planner) -> None:
        self.planner = planner
        self.last_stats = planner.last_stats

    def plan(
        self,
        topic: str,
        depth_level: int = 2,
        research_id: str | None = None,
    ):
        plan = self.planner.plan(
            topic,
            depth_level,
            research_id=research_id,
        )
        plan.sub_questions[0].structured_data_requests = [
            StructuredDataRequest(
                capability="financial_indicators",
                symbol="300750",
            )
        ]
        return plan


class ExpandedTrajectoryTest(unittest.TestCase):
    def test_strict_schema_rejects_missing_fields_order_version_and_prompt_mutation(
        self,
    ) -> None:
        recorder = TrajectoryRecorder(
            run_id="synthetic-strict-fixture",
            request={
                "topic": "synthetic trajectory fixture",
                "mode": "deterministic",
                "depth_level": 1,
                "recorded_plan": {"topic": "synthetic trajectory fixture", "depth_level": 1, "sub_questions": [{"id": "q", "question": "q", "search_queries": ["q"], "expected_source_types": ["official"]}], "estimated_sources": 6, "success_criteria": ["citation"]},
                "synthetic": True,
                "provider": "fake",
            },
        )
        recorder.record_llm_call(
            LLMCallTrace(
                role="fake_planner",
                prompt=[{"role": "user", "content": "fixed fake prompt"}],
                response="{}", prompt_tokens=0, completion_tokens=0,
                total_tokens=0, latency_seconds=0, model="fake", attempt=1,
            )
        )
        recorder.finalize(manifest_ref=None, artifacts={"report.md": "synthetic"})
        valid = recorder.trajectory
        validate_strict_replay_trajectory(valid)
        self.assertEqual(valid.schema_version, 5)
        self.assertEqual(valid.termination.status, "completed")
        missing_termination = valid.model_copy(
            update={"termination": None}
        )
        with self.assertRaisesRegex(ValueError, "termination missing"):
            validate_strict_replay_trajectory(missing_termination)
        missing = valid.model_copy(deep=True)
        missing.request.pop("recorded_plan")
        with self.assertRaisesRegex(ValueError, "request missing required field"):
            validate_strict_replay_trajectory(missing)
        wrong_version = valid.model_copy(update={"schema_version": 2})
        with self.assertRaisesRegex(ValueError, "schema_version mismatch"):
            validate_strict_replay_trajectory(wrong_version)
        changed_prompt = valid.model_copy(deep=True)
        changed_prompt.llm_calls[0].prompt[0]["content"] += "!"
        with self.assertRaisesRegex(ValueError, "normalized_key mismatch"):
            validate_strict_replay_trajectory(changed_prompt)
        legacy_v4 = valid.model_copy(update={"schema_version": 4})
        validate_strict_replay_trajectory(legacy_v4)
        legacy_rag = legacy_v4.model_copy(deep=True)
        legacy_rag.request["strategy_config"] = {"rag_enabled": True}
        with self.assertRaisesRegex(ValueError, "v4 trajectory cannot replay with RAG enabled"):
            validate_strict_replay_trajectory(legacy_rag)
        bad_order = valid.model_copy(deep=True)
        bad_order.llm_calls[0].sequence = 2
        with self.assertRaisesRegex(ValueError, "sequence mismatch"):
            validate_strict_replay_trajectory(bad_order)

    def test_expanded_016_configuration_is_complete_and_strictly_replays(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                storage_path=root / "record.db",
                runs_root=root / "runs",
                as_of=date(2026, 7, 9),
                trajectory_record_enabled=True,
                structured_logging_enabled=False,
                max_critic_iter=1,
                research_loop_enabled=True,
                research_loop_max_iterations=2,
                research_loop_budget_ceiling=20,
                research_loop_no_progress_window=5,
                research_min_evidence_count=99,
                decision_weaving_enabled=True,
                numeric_check_enabled=True,
                dynamic_capability_enabled=True,
                semantic_judge_enabled=True,
                context_packer_enabled=True,
                reporter_context_token_budget=12_345,
                prior_memory_enabled=True,
            )
            engine = DeepResearchEngine(
                settings=settings,
                structured_data_provider=NumericRelationProvider(),
            )
            engine.planner = StructuredPlanner(engine.planner)
            state = engine.run(
                topic="宁德时代 2024 年业绩与欧洲工厂扩张研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                root
                / "runs"
                / state.research_id
                / "trajectory.json"
            )

            decision_types = [
                item.decision_type
                for item in trajectory.agent_decisions
            ]
            tool_names = [
                str(item.tool_spec.get("name"))
                for item in trajectory.tool_calls
            ]
            node_names = [
                item.node for item in trajectory.node_transitions
            ]

            self.assertEqual(trajectory.llm_calls, [])
            self.assertIn("web_search", tool_names)
            self.assertIn("structured_data_provider", tool_names)
            self.assertGreaterEqual(
                node_names.count("research_prepare"),
                2,
            )
            self.assertIn("capability_selection", decision_types)
            self.assertIn("numeric_consistency_check", decision_types)
            self.assertIn("numeric_consistency_scan", decision_types)
            self.assertIn("branch_budget_reallocate", decision_types)
            self.assertIn("bounded_loop_control", decision_types)
            self.assertIn("research_replan", decision_types)
            self.assertEqual(
                len(trajectory.agent_decisions),
                len(state.agent_decisions),
            )
            self.assertEqual(
                len(trajectory.tool_calls),
                tool_names.count("web_search")
                + tool_names.count("web_fetch")
                + tool_names.count("structured_data_provider"),
            )
            strategy_config = trajectory.request["strategy_config"]
            self.assertEqual(
                {
                    key: strategy_config[key]
                    for key in (
                        "semantic_judge_enabled",
                        "context_packer_enabled",
                        "reporter_context_token_budget",
                        "prior_memory_enabled",
                    )
                },
                {
                    "semantic_judge_enabled": True,
                    "context_packer_enabled": True,
                    "reporter_context_token_budget": 12_345,
                    "prior_memory_enabled": True,
                },
            )
            self.assertIsNone(
                trajectory.request["prior_memory_snapshot"]
            )

            replay = replay_trajectory(trajectory, mode="strict")

        self.assertEqual(
            replay.status,
            "reproduced",
            replay.cache_miss,
        )
        self.assertEqual(replay.artifact_matches, {"report.md": True})

    def test_schema_reserves_017_signal_and_memory_and_018_mcp_calls(
        self,
    ) -> None:
        recorder = TrajectoryRecorder(
            run_id="forward-schema",
            request={"topic": "forward"},
        )
        recorder.record_signal_read(
            SignalReadTrace(
                signal_type="repeated_critic_issue",
                source="AgentTrajectory.agent_decisions",
                keys=("issue_type", "iteration"),
            )
        )
        recorder.record_memory_write(
            MemoryWriteTrace(
                memory_type="procedural",
                lifecycle="cross_run",
                key={"question_type": "financial_metric"},
                value_summary={"sufficiency_delta": 0.1},
            )
        )
        recorder.record_tool_call(
            ToolCallTrace(
                tool_spec={"name": "external_quote_lookup"},
                inputs={"symbol": "300750"},
                result={"ok": True},
                attempts=1,
                transport="mcp",
                server="fixture-mcp",
            )
        )

        self.assertEqual(recorder.trajectory.schema_version, 5)
        self.assertEqual(
            recorder.trajectory.signal_reads[0].signal_type,
            "repeated_critic_issue",
        )
        self.assertEqual(
            recorder.trajectory.memory_writes[0].lifecycle,
            "cross_run",
        )
        self.assertEqual(
            recorder.trajectory.tool_calls[0].transport,
            "mcp",
        )

    def test_legacy_v3_fixture_remains_read_only_compatible(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "trajectories"
            / "synthetic"
            / "fake_provider_synthetic_trajectory.json"
        )

        trajectory = load_trajectory(fixture)
        validate_strict_replay_trajectory(trajectory)

        self.assertEqual(trajectory.schema_version, 3)
        self.assertIsNone(trajectory.termination)

    def test_v4_budget_and_failure_termination_contracts(self) -> None:
        request = {
            "topic": "termination",
            "mode": "deterministic",
            "depth_level": 1,
            "recorded_plan": {
                "topic": "termination",
                "depth_level": 1,
                "sub_questions": [
                    {
                        "id": "q",
                        "question": "q",
                        "search_queries": ["q"],
                        "expected_source_types": ["official"],
                    }
                ],
                "estimated_sources": 1,
                "success_criteria": [],
            },
        }
        budget = TrajectoryRecorder(
            run_id="budget-termination",
            request=request,
        )
        budget.finalize(
            manifest_ref=None,
            artifacts={"report.md": "partial"},
            termination=TrajectoryTermination(
                status="budget_exceeded",
                phase="researching",
                error_type="ToolExecutionError",
                error_message="budget exhausted",
            ),
        )
        validate_strict_replay_trajectory(budget.trajectory)

        failed = TrajectoryRecorder(
            run_id="failed-termination",
            request=request,
        )
        failed.terminate(
            TrajectoryTermination(
                status="failed",
                phase="extracting",
                error_type="RuntimeError",
                error_message="fixture failure",
            )
        )
        validate_strict_replay_trajectory(failed.trajectory)

        with self.assertRaisesRegex(
            ValueError,
            "requires error_type and error_message",
        ):
            TrajectoryTermination(
                status="failed",
                phase="extracting",
            )

    def test_expanded_018_mcp_and_skill_trace_strictly_replays(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                storage_path=root / "record.db",
                runs_root=root / "runs",
                as_of=date(2026, 7, 9),
                trajectory_record_enabled=True,
                structured_logging_enabled=False,
                run_manifest_enabled=False,
                max_critic_iter=1,
                skill_packs_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings)
            state = engine.run(
                topic="宁德时代 2024 年营收与归母净利润研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                root
                / "runs"
                / state.research_id
                / "trajectory.json"
            )

            recorder = TrajectoryRecorder(
                run_id=trajectory.run_id,
                request=trajectory.request,
            )
            recorder.trajectory = trajectory
            environ = dict(os.environ)
            environ["PYTHONPATH"] = str(
                Path(__file__).resolve().parents[2] / "src"
            )
            client = MCPStdioClient(
                [
                    sys.executable,
                    "-m",
                    "deepresearch_agent.mcp.server",
                    "--runtime-root",
                    str(root / "mcp-runtime"),
                ],
                server_name="self-fixture",
                request_timeout_s=10.0,
                environ=environ,
            )
            try:
                with trajectory_recording(recorder):
                    client.discover_and_register(
                        engine.capability_registry,
                        state,
                        trusted_server=True,
                        executor=ReliableToolExecutor(
                            sleep=lambda _seconds: None,
                        ),
                    )
                    tool = engine.capability_registry.resolve(
                        "mcp.self-fixture.research.start"
                    )
                    mcp_result = tool.call(
                        {
                            "topic": (
                                "宁德时代 2024 年业绩与欧洲工厂扩张研究"
                            ),
                            "depth_level": 1,
                            "execution_mode": "deterministic",
                            "allow_paid": False,
                        },
                        allow_paid=True,
                    )
            finally:
                client.close()
            recorder.finalize(
                manifest_ref=trajectory.run_manifest_ref,
                artifacts=trajectory.artifacts,
            )
            expanded = recorder.trajectory

            decision_types = {
                item.decision_type
                for item in expanded.agent_decisions
            }
            mcp_calls = [
                item
                for item in expanded.tool_calls
                if item.transport == "mcp"
            ]
            self.assertTrue(mcp_result.ok)
            self.assertIn("skill_selection", decision_types)
            self.assertIn("skill_load", decision_types)
            self.assertIn("mcp_tool_discovery", decision_types)
            self.assertEqual(1, len(mcp_calls))
            self.assertEqual(
                "self-fixture",
                mcp_calls[0].server,
            )
            replay = replay_trajectory(
                expanded,
                mode="strict",
                required_calls=[
                    "tool:mcp.self-fixture.research.start"
                ],
            )

        self.assertEqual(
            replay.status,
            "reproduced",
            replay.cache_miss,
        )
        self.assertEqual(replay.artifact_matches, {"report.md": True})

    def test_expanded_017_configuration_captures_and_strictly_replays(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                storage_path=root / "record.db",
                runs_root=root / "runs",
                as_of=date(2026, 7, 9),
                trajectory_record_enabled=True,
                structured_logging_enabled=False,
                max_critic_iter=1,
                research_loop_enabled=True,
                research_loop_max_iterations=2,
                research_loop_budget_ceiling=20,
                research_loop_no_progress_window=5,
                research_min_evidence_count=99,
                decision_weaving_enabled=True,
                numeric_check_enabled=True,
                dynamic_capability_enabled=True,
                reflection_enabled=True,
                procedural_memory_enabled=True,
            )
            engine = DeepResearchEngine(
                settings=settings,
                structured_data_provider=NumericRelationProvider(),
            )
            engine.planner = StructuredPlanner(engine.planner)
            state = engine.run(
                topic="宁德时代 2024 年业绩与欧洲工厂扩张研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                root
                / "runs"
                / state.research_id
                / "trajectory.json"
            )

            decision_types = {
                item.decision_type
                for item in trajectory.agent_decisions
            }
            signal_types = {
                item.signal_type for item in trajectory.signal_reads
            }
            llm_roles = {item.role for item in trajectory.llm_calls}
            node_names = {
                item.node for item in trajectory.node_transitions
            }

            self.assertIn("reflector", node_names)
            self.assertIn(
                "reflection_signal_extraction",
                decision_types,
            )
            self.assertIn("procedural_memory_write", decision_types)
            self.assertEqual(
                signal_types,
                {
                    "persistent_weakness",
                    "ineffective_source",
                    "repeated_critic_issue",
                    "ineffective_replanning",
                },
            )
            self.assertEqual(
                {item.memory_type for item in trajectory.memory_writes},
                {"procedural"},
            )
            self.assertEqual(
                {
                    item.lifecycle
                    for item in trajectory.memory_writes
                },
                {"cross_run"},
            )
            self.assertEqual(
                llm_roles,
                {"reflector_placeholder"},
            )
            self.assertTrue(
                all(
                    item.total_tokens == 0
                    and item.model == "synthetic_fixture"
                    for item in trajectory.llm_calls
                )
            )

            replay = replay_trajectory(
                trajectory,
                mode="strict",
                required_calls=["llm:reflector_placeholder"],
            )

        self.assertEqual(
            replay.status,
            "reproduced",
            replay.cache_miss,
        )
        self.assertEqual(replay.artifact_matches, {"report.md": True})


if __name__ == "__main__":
    unittest.main()
