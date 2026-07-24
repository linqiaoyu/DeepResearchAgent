from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.reflection import Reflector, ReflectionResult
from deepresearch_agent.schemas import AgentDecision
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import AgentTrajectory
from deepresearch_agent.workflow import DeepResearchEngine


class ReflectionSkeletonTest(unittest.TestCase):
    def _trajectory(self) -> AgentTrajectory:
        return AgentTrajectory(
            run_id="reflection-run",
            request={"topic": "reflection fixture"},
        )

    def _decision(self) -> AgentDecision:
        return AgentDecision(
            decision_type="fixture",
            made_by="FixtureAgent",
            inputs={"round": 1},
            criterion="fixture criterion",
            outcome="fixture outcome",
        )

    def test_result_has_dual_track_pending_structure(self) -> None:
        result = Reflector().reflect(
            self._trajectory(),
            [self._decision()],
        )

        self.assertIsInstance(result, ReflectionResult)
        self.assertEqual(
            result.deterministic_signals.model_dump(),
            {
                "persistently_weak_subquestions": [],
                "repeatedly_ineffective_sources": [],
                "repeated_critic_issue_types": {},
                "ineffective_replanning_iterations": [],
            },
        )
        self.assertEqual(
            result.llm_insight.status,
            "pending_llm_reasoning",
        )
        self.assertEqual(
            result.llm_insight.quality_validation,
            "unverifiable_in_deterministic_mode",
        )

    def test_reflector_does_not_mutate_trajectory_or_decisions(self) -> None:
        trajectory = self._trajectory()
        decisions = [self._decision()]
        before_trajectory = trajectory.model_dump_json()
        before_decisions = [item.model_dump_json() for item in decisions]

        Reflector().reflect(trajectory, decisions)

        self.assertEqual(trajectory.model_dump_json(), before_trajectory)
        self.assertEqual(
            [item.model_dump_json() for item in decisions],
            before_decisions,
        )

    def test_contract_declares_decisions_and_additive_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(temp_dir) / "reflection.db",
                    runs_root=Path(temp_dir) / "runs",
                    reflection_enabled=True,
                    structured_logging_enabled=False,
                )
            )
            contract = engine.node_contracts["reflector"]
            engine._checkpoint_conn.close()

        self.assertIn(
            "research_state.agent_decisions",
            contract.consumes,
        )
        self.assertEqual(
            contract.produces,
            frozenset({"research_state.metadata.reflection_result"}),
        )
        self.assertFalse(contract.decision_node)

    def test_enabled_engine_emits_additive_result_without_persisting_trace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=root / "reflection.db",
                    runs_root=root / "runs",
                    reflection_enabled=True,
                    structured_logging_enabled=False,
                )
            )
            state = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()

            self.assertEqual(
                state.metadata["reflection_result"]["llm_insight"][
                    "status"
                ],
                "pending_llm_reasoning",
            )
            self.assertFalse(
                (
                    root
                    / "runs"
                    / state.research_id
                    / "trajectory.json"
                ).exists()
            )

    def test_default_switch_is_off(self) -> None:
        self.assertFalse(
            Settings(storage_path=Path("test.db")).reflection_enabled
        )


if __name__ == "__main__":
    unittest.main()
