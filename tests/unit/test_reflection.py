from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.orchestration import (
    SufficiencyThresholds,
    evaluate_research_sufficiency,
)
from deepresearch_agent.reflection import Reflector, ReflectionResult
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import (
    AgentTrajectory,
    NodeTransitionTrace,
    ToolCallTrace,
)
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
            frozenset(
                {
                    "research_state.metadata.reflection_result",
                    "research_state.agent_decisions",
                }
            ),
        )
        self.assertTrue(contract.decision_node)

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
            self.assertEqual(
                state.agent_decisions[-1].decision_type,
                "reflection_signal_extraction",
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


class DeterministicSignalExtractionTest(unittest.TestCase):
    def _decisions(self) -> list[AgentDecision]:
        return [
            AgentDecision(
                decision_type="research_replan",
                made_by="PlannerAgent",
                inputs={
                    "gaps_by_sub_question": {
                        "weak": ["evidence_count"],
                        "improving": ["freshness"],
                    }
                },
                criterion="fixture",
                outcome="fixture",
                iteration=2,
            ),
            AgentDecision(
                decision_type="bounded_loop_control",
                made_by="BoundedLoop",
                inputs={"metric_before": 0.4, "metric_after": 0.4},
                criterion="fixture",
                outcome="continue",
                iteration=2,
            ),
            AgentDecision(
                decision_type="research_replan",
                made_by="PlannerAgent",
                inputs={
                    "gaps_by_sub_question": {
                        "weak": ["average_confidence"],
                        "improving": [],
                    }
                },
                criterion="fixture",
                outcome="fixture",
                iteration=3,
            ),
            AgentDecision(
                decision_type="bounded_loop_control",
                made_by="BoundedLoop",
                inputs={"metric_before": 0.4, "metric_after": 0.6},
                criterion="fixture",
                outcome="stop",
                iteration=3,
            ),
        ]

    def _trajectory(self) -> AgentTrajectory:
        bad_source = {
            "url": "https://bad.example/article",
            "title": "bad",
        }
        return AgentTrajectory(
            run_id="signals",
            request={"topic": "signals"},
            tool_calls=[
                ToolCallTrace(
                    tool_spec={"name": "web_search"},
                    inputs={"query": "one"},
                    result=[bad_source],
                    attempts=1,
                ),
                ToolCallTrace(
                    tool_spec={"name": "web_search"},
                    inputs={"query": "two"},
                    result=[
                        bad_source,
                        {
                            "url": "https://good.example/article",
                            "title": "good",
                        },
                    ],
                    attempts=1,
                ),
            ],
            node_transitions=[
                NodeTransitionTrace(
                    node="extractor",
                    input_summary={},
                    output_summary={
                        "evidence_source_domains": ["good.example"]
                    },
                ),
                NodeTransitionTrace(
                    node="critic",
                    input_summary={},
                    output_summary={
                        "critic_issue_types": [
                            "missing_citation",
                            "numeric_conflict",
                        ]
                    },
                ),
                NodeTransitionTrace(
                    node="critic",
                    input_summary={},
                    output_summary={
                        "critic_issue_types": ["missing_citation"]
                    },
                ),
            ],
        )

    def test_extracts_all_four_mechanical_signal_categories(self) -> None:
        result = Reflector().reflect(
            self._trajectory(),
            self._decisions(),
        )

        self.assertEqual(
            result.deterministic_signals.model_dump(),
            {
                "persistently_weak_subquestions": ["weak"],
                "repeatedly_ineffective_sources": ["bad.example"],
                "repeated_critic_issue_types": {
                    "missing_citation": 2
                },
                "ineffective_replanning_iterations": [2],
            },
        )

    def test_same_trajectory_and_decisions_produce_same_signals(self) -> None:
        first = Reflector().reflect(
            self._trajectory(),
            self._decisions(),
        )
        second = Reflector().reflect(
            self._trajectory(),
            self._decisions(),
        )

        self.assertEqual(
            first.deterministic_signals.model_dump_json(),
            second.deterministic_signals.model_dump_json(),
        )

    def test_signal_decision_records_sources_even_when_signals_empty(
        self,
    ) -> None:
        trajectory = AgentTrajectory(
            run_id="empty",
            request={"topic": "empty"},
        )
        result = Reflector().reflect(trajectory, [])

        decision = Reflector().signal_extraction_decision(
            trajectory,
            [],
            result.deterministic_signals,
        )

        self.assertEqual(
            decision.decision_type,
            "reflection_signal_extraction",
        )
        self.assertEqual(
            decision.inputs["signal_sources"],
            [
                "AgentTrajectory.tool_calls",
                "AgentTrajectory.node_transitions",
                "ResearchState.agent_decisions",
            ],
        )
        self.assertEqual(
            decision.inputs["signal_counts"],
            {
                "persistently_weak_subquestions": 0,
                "repeatedly_ineffective_sources": 0,
                "repeated_critic_issue_types": 0,
                "ineffective_replanning_iterations": 0,
            },
        )

    def test_single_round_sufficiency_is_not_cross_round_reflection(
        self,
    ) -> None:
        state = ResearchState(topic="different time horizons")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="weak",
                    question="weak now?",
                    search_queries=["weak"],
                )
            ],
        )
        state.evidence_store = [
            Evidence(
                id="e",
                research_id=state.research_id,
                sub_question_id="weak",
                claim="one observation",
                claim_type="fact",
                source_url="https://one.example/a",
                source_title="one",
                source_pub_date=date(2026, 7, 24),
                extract_text="one observation",
            )
        ]
        sufficiency = evaluate_research_sufficiency(
            state,
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(min_evidence_count=2),
        )
        one_round = [
            AgentDecision(
                decision_type="research_replan",
                made_by="PlannerAgent",
                inputs={
                    "gaps_by_sub_question": {
                        "weak": ["evidence_count"]
                    }
                },
                criterion="fixture",
                outcome="fixture",
                iteration=2,
            )
        ]
        reflection = Reflector().reflect(self._trajectory(), one_round)

        self.assertFalse(sufficiency.by_sub_question[0].sufficient)
        self.assertEqual(
            reflection.deterministic_signals.persistently_weak_subquestions,
            [],
        )


if __name__ == "__main__":
    unittest.main()
