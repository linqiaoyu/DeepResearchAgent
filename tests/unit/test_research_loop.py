from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.orchestration import (
    SufficiencyThresholds,
    evaluate_research_sufficiency,
    refine_research_plan,
)
from deepresearch_agent.provenance import settings_flag_snapshot
from deepresearch_agent.schemas import (
    CriticReport,
    Evidence,
    Issue,
    ResearchPlan,
    ResearchState,
    RetryTask,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


def _state(evidence: list[Evidence]) -> ResearchState:
    state = ResearchState(topic="研究充分性")
    state.plan = ResearchPlan(
        topic=state.topic,
        sub_questions=[
            SubQuestion(
                id="sq-1",
                question="业绩是否改善",
                search_queries=["original query"],
            )
        ],
    )
    state.evidence_store = evidence
    return state


def _evidence(
    item_id: str,
    *,
    url: str = "https://one.example/a",
    confidence: float = 0.8,
    published: date = date(2026, 7, 1),
    claim: str = "业绩改善",
) -> Evidence:
    return Evidence(
        id=item_id,
        research_id="run",
        sub_question_id="sq-1",
        claim=claim,
        claim_type="fact",
        source_url=url,
        source_title=item_id,
        source_pub_date=published,
        extract_text=claim,
        confidence=confidence,
    )


class ResearchSufficiencyTest(unittest.TestCase):
    def test_sufficiency_score_is_sensitive_before_components_saturate(
        self,
    ) -> None:
        thresholds = SufficiencyThresholds()
        one_source = evaluate_research_sufficiency(
            _state([_evidence("a", claim="主要风险是监管限制")]),
            as_of=date(2026, 7, 24),
            thresholds=thresholds,
        )
        two_sources = evaluate_research_sufficiency(
            _state(
                [
                    _evidence("a", claim="主要风险是监管限制"),
                    _evidence(
                        "b",
                        url="https://two.example/b",
                        claim="业绩改善",
                    ),
                ]
            ),
            as_of=date(2026, 7, 24),
            thresholds=thresholds,
        )

        self.assertEqual(one_source.score, 0.833333)
        self.assertEqual(two_sources.score, 1.0)
        self.assertGreater(two_sources.score, one_source.score)

    def test_metric_evidence_count(self) -> None:
        result = evaluate_research_sufficiency(
            _state([_evidence("a")]),
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(min_evidence_count=2),
        )
        metrics = result.by_sub_question[0]
        self.assertEqual(metrics.evidence_count, 1)
        self.assertIn("evidence_count", metrics.gaps)

    def test_metric_independent_source_domains(self) -> None:
        result = evaluate_research_sufficiency(
            _state(
                [
                    _evidence("a", url="https://same.example/a"),
                    _evidence("b", url="https://same.example/b"),
                ]
            ),
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        metrics = result.by_sub_question[0]
        self.assertEqual(metrics.independent_source_domains, 1)
        self.assertIn("independent_source_domains", metrics.gaps)

    def test_metric_average_confidence(self) -> None:
        result = evaluate_research_sufficiency(
            _state(
                [
                    _evidence("a", confidence=0.4),
                    _evidence(
                        "b",
                        confidence=0.6,
                        url="https://two.example/b",
                    ),
                ]
            ),
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(
                min_average_confidence=0.7
            ),
        )
        metrics = result.by_sub_question[0]
        self.assertEqual(metrics.average_confidence, 0.5)
        self.assertIn("average_confidence", metrics.gaps)

    def test_metric_freshest_evidence_age(self) -> None:
        result = evaluate_research_sufficiency(
            _state(
                [
                    _evidence("a", published=date(2024, 1, 1)),
                    _evidence(
                        "b",
                        url="https://two.example/b",
                        published=date(2025, 1, 1),
                    ),
                ]
            ),
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(
                max_freshness_age_days=365
            ),
        )
        metrics = result.by_sub_question[0]
        self.assertEqual(metrics.freshest_evidence_age_days, 569)
        self.assertIn("freshness", metrics.gaps)

    def test_metric_unresolved_critic_issues(self) -> None:
        state = _state(
            [
                _evidence("a"),
                _evidence("b", url="https://two.example/b"),
            ]
        )
        task = RetryTask(
            reason="gap",
            query="verify",
            sub_question_id="sq-1",
        )
        state.critic_report = CriticReport(
            passed=False,
            overall_quality=0.5,
            issues=[
                Issue(
                    issue_type="missing_citation",
                    severity="high",
                    message="gap",
                    suggested_retry_task=task,
                )
            ],
            retry_tasks=[task],
        )
        result = evaluate_research_sufficiency(
            state,
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        metrics = result.by_sub_question[0]
        self.assertEqual(metrics.unresolved_critic_issues, 1)
        self.assertIn("unresolved_critic_issues", metrics.gaps)

    def test_metric_missing_counterargument(self) -> None:
        without = evaluate_research_sufficiency(
            _state(
                [
                    _evidence("a"),
                    _evidence("b", url="https://two.example/b"),
                ]
            ),
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        with_counter = evaluate_research_sufficiency(
            _state(
                [
                    _evidence("a"),
                    _evidence(
                        "b",
                        url="https://two.example/b",
                        claim="主要风险是监管限制",
                    ),
                ]
            ),
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        self.assertTrue(
            without.by_sub_question[0].missing_counterargument
        )
        self.assertFalse(
            with_counter.by_sub_question[0].missing_counterargument
        )

    def test_replanning_replaces_instead_of_repeating_queries(self) -> None:
        state = _state([_evidence("a")])
        sufficiency = evaluate_research_sufficiency(
            state,
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        previous = list(state.plan.sub_questions[0].search_queries)

        refined = refine_research_plan(
            state,
            sufficiency,
            as_of=date(2026, 7, 24),
            iteration=2,
        )

        self.assertNotEqual(refined["sq-1"], previous)
        self.assertTrue(
            all(query not in previous for query in refined["sq-1"])
        )
        self.assertEqual(
            state.agent_decisions[-1].decision_type,
            "research_replan",
        )

    def test_max_iterations_one_is_effectively_byte_compatible_off(self) -> None:
        settings = Settings(
            storage_path=Path("test.db"),
            research_loop_enabled=True,
            research_loop_max_iterations=1,
        )
        self.assertFalse(settings.research_loop_active)
        self.assertNotIn(
            "RESEARCH_LOOP_ENABLED",
            settings_flag_snapshot(settings),
        )

    def test_enabled_engine_replans_and_reports_two_distinct_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                as_of=date(2026, 7, 24),
                research_loop_enabled=True,
                research_loop_max_iterations=2,
                research_loop_budget_ceiling=20,
                research_loop_no_progress_window=5,
                research_min_evidence_count=99,
                research_min_independent_domains=99,
                research_min_average_confidence=1.0,
                research_max_freshness_age_days=0,
                max_critic_iter=1,
                structured_logging_enabled=False,
            )
            engine = DeepResearchEngine(settings=settings)
            state = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()

        process = state.metadata["research_process"]
        self.assertEqual(len(process), 2)
        first_queries = process[0]["queries"]
        second_queries = process[1]["queries"]
        self.assertNotEqual(first_queries, second_queries)
        for sub_question_id, queries in second_queries.items():
            self.assertTrue(
                all(
                    query not in first_queries[sub_question_id]
                    for query in queries
                )
            )
        decision_types = [
            item.decision_type for item in state.agent_decisions
        ]
        self.assertIn("research_replan", decision_types)
        self.assertIn("bounded_loop_control", decision_types)
        self.assertIn("## 研究过程", state.final_report or "")
        self.assertIn("第 2 轮", state.final_report or "")
        self.assertIn("stop_exhausted:max_iterations", state.final_report or "")


if __name__ == "__main__":
    unittest.main()
