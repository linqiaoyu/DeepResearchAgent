from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from deepresearch_agent.agents import CriticAgent, ResearcherAgent
from deepresearch_agent.memory import (
    EpisodicMemory,
    EpisodicRecord,
    classify_subquestions_from_prior,
)
from deepresearch_agent.provenance import RunManifest
from deepresearch_agent.research_snapshot import (
    NormalizedClaimKey,
    ResearchSnapshot,
    SnapshotClaim,
    research_question_id,
)
from deepresearch_agent.schemas import (
    ComparisonTable,
    EventTimeline,
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    RiskMatrix,
    Source,
    StructuredResearchOutput,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import load_trajectory
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


def _manifest() -> RunManifest:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    return RunManifest(
        run_id="prior",
        started_at=now,
        ended_at=now,
        model_strings={},
        prompt_hashes={},
        config_hash="config",
        dependency_versions={},
        domain="finance",
        mode="deterministic",
        flags={},
        token_total=0,
        cost_cny_total=0,
    )


def _snapshot(
    question: str,
    claims: list[SnapshotClaim],
) -> ResearchSnapshot:
    return ResearchSnapshot(
        question_id=research_question_id(question),
        question=question,
        as_of=date(2026, 7, 9),
        claims=claims,
        structured_objects=StructuredResearchOutput(
            comparison_table=ComparisonTable(question=question),
            event_timeline=EventTimeline(question=question),
            risk_matrix=RiskMatrix(question=question),
        ),
        manifest_ref="prior-manifest",
        manifest=_manifest(),
        flags={},
    )


def _claim(
    claim_id: str,
    text: str,
    *,
    confidence: float,
    value: float | None = None,
    scope: str = "全年",
    sources: list[str] | None = None,
) -> SnapshotClaim:
    return SnapshotClaim(
        claim_id=claim_id,
        key=NormalizedClaimKey(
            entity="宁德时代",
            metric=text,
            period="2024",
            scope=scope,
        ),
        text=text,
        value=value,
        unit="亿元" if value is not None else None,
        source_urls=sources or [],
        confidence=confidence,
        thesis_direction=(
            "uncertain" if confidence < 0.7 else "neutral"
        ),
    )


def _numeric_evidence(
    *,
    value: float,
    scope: str = "全年",
    claim: str = "营收为120亿元",
) -> Evidence:
    return Evidence(
        id=f"current-{scope}-{value}",
        research_id="current",
        sub_question_id="verify",
        claim=claim,
        claim_type="data",
        source_kind="structured",
        source_url="akshare://营收/current",
        source_title="current",
        source_pub_date=date(2026, 7, 24),
        extract_text=claim,
        confidence=0.98,
        numeric_fields=NumericFields(
            entity="宁德时代",
            metric_name="营收",
            period="2024",
            dimension=scope,
            value=value,
            unit="亿元",
        ),
    )


class TrackingProvider:
    def __init__(self) -> None:
        self.fetches: list[str] = []
        self.searches: list[str] = []
        self.source = Source(
            id="old",
            title="old",
            url="https://prior.example/revenue",
            source_type="official",
            published_at=date(2026, 7, 1),
            content="营收",
        )

    def fetch(self, url: str, **_kwargs: object):
        self.fetches.append(url)
        return self.source if url == self.source.url else None

    def search(
        self,
        query: str,
        top_k: int = 3,
        source_type: str | None = None,
        **_kwargs: object,
    ):
        self.searches.append(query)
        return []


class PriorMemoryTest(unittest.TestCase):
    def test_classifies_verify_explore_watch_with_visible_criteria(self) -> None:
        state = ResearchState(topic="跨期")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="verify",
                    question="核实营收",
                    search_queries=["营收"],
                ),
                SubQuestion(
                    id="watch",
                    question="关注利润",
                    search_queries=["利润"],
                ),
                SubQuestion(
                    id="explore",
                    question="欧洲工厂",
                    search_queries=["欧洲工厂"],
                ),
            ],
        )
        snapshot = _snapshot(
            state.topic,
            [
                _claim(
                    "revenue",
                    "营收",
                    confidence=0.9,
                    sources=["https://prior.example/revenue"],
                ),
                _claim("profit", "利润", confidence=0.5),
            ],
        )

        classifications = classify_subquestions_from_prior(
            state,
            snapshot,
        )

        self.assertEqual(
            [item.kind for item in classifications],
            ["verify", "watch", "explore"],
        )
        self.assertEqual(
            classifications[0].priority_urls,
            ["https://prior.example/revenue"],
        )
        self.assertEqual(len(state.agent_decisions), 3)
        self.assertTrue(
            all(item.inputs["prior_as_of"] == "2026-07-09" for item in state.agent_decisions)
        )

    def test_verify_priority_url_still_keeps_independent_search(self) -> None:
        provider = TrackingProvider()
        researcher = ResearcherAgent(search_tool=provider)
        sub_question = SubQuestion(
            id="verify",
            question="核实营收",
            search_queries=["independent revenue search"],
        )

        _, records, calls, _, _decisions = researcher.research_with_budget(
            sub_question,
            max_search_calls=2,
            priority_urls=["https://prior.example/revenue"],
        )

        self.assertEqual(provider.fetches, ["https://prior.example/revenue"])
        self.assertEqual(provider.searches, ["independent revenue search"])
        self.assertEqual(calls, 2)
        self.assertEqual(
            [item.query for item in records],
            [
                "[priority_url] https://prior.example/revenue",
                "independent revenue search",
            ],
        )

    def test_critic_detects_same_four_key_unexplained_contradiction(self) -> None:
        snapshot = _snapshot(
            "跨期",
            [
                _claim(
                    "revenue",
                    "营收",
                    confidence=0.9,
                    value=100,
                )
            ],
        )
        state = ResearchState(topic="跨期")
        state.evidence_store = [_numeric_evidence(value=120)]
        state.metadata["prior_memory"] = {
            "snapshot": snapshot.model_dump(mode="json")
        }

        report = CriticAgent(today=date(2026, 7, 24)).critique(state)
        contradictions = [
            item
            for item in report.issues
            if item.issue_type == "contradicts_prior"
        ]

        self.assertEqual(len(contradictions), 1)
        self.assertIsNotNone(contradictions[0].suggested_retry_task)
        self.assertEqual(
            contradictions[0].suggested_retry_task.sub_question_id,
            "verify",
        )

    def test_critic_ignores_same_value_different_scope_and_explained_change(
        self,
    ) -> None:
        snapshot = _snapshot(
            "跨期",
            [
                _claim(
                    "revenue",
                    "营收",
                    confidence=0.9,
                    value=100,
                )
            ],
        )
        critic = CriticAgent(today=date(2026, 7, 24))
        candidates = [
            _numeric_evidence(value=100),
            _numeric_evidence(value=120, scope="单季"),
            _numeric_evidence(
                value=120,
                claim="营收同比增长，因此变为120亿元",
            ),
        ]
        for evidence in candidates:
            with self.subTest(evidence=evidence.id):
                state = ResearchState(topic="跨期")
                state.evidence_store = [evidence]
                state.metadata["prior_memory"] = {
                    "snapshot": snapshot.model_dump(mode="json")
                }
                report = critic.critique(state)
                self.assertFalse(
                    any(
                        item.issue_type == "contradicts_prior"
                        for item in report.issues
                    )
                )

    def test_enabled_engine_uses_latest_prior_and_reports_agent_difference(
        self,
    ) -> None:
        topic = "AI Agent 在财富管理行业的落地机会研究"
        memory = EpisodicMemory()
        memory.write(
            EpisodicRecord(
                snapshot=_snapshot(
                    topic,
                    [
                        _claim(
                            "advisor",
                            "AI Agent 财富管理",
                            confidence=0.9,
                            sources=["https://example.com/wealth"],
                        )
                    ],
                ),
                trajectory_ref="runs/prior/trajectory.json",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    runs_root=Path(tmp) / "runs",
                    as_of=date(2026, 7, 24),
                    prior_memory_enabled=True,
                    trajectory_record_enabled=True,
                    run_manifest_enabled=False,
                    max_critic_iter=1,
                    structured_logging_enabled=False,
                ),
                episodic_memory=memory,
            )
            state = engine.run(topic=topic, depth_level=1)
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                Path(tmp)
                / "runs"
                / state.research_id
                / "trajectory.json"
            )
            replay = replay_trajectory(trajectory, mode="strict")

        self.assertEqual(state.metadata["prior_memory"]["as_of"], "2026-07-09")
        self.assertNotIn("## 与上期结论的差异", state.final_report or "")
        self.assertTrue(state.metadata["prior_memory"]["classifications"])
        self.assertIn("snapshot", state.metadata["prior_memory"])
        self.assertEqual(
            trajectory.request["prior_memory_snapshot"]["as_of"],
            "2026-07-09",
        )
        self.assertEqual(replay.status, "reproduced", replay.cache_miss)


if __name__ == "__main__":
    unittest.main()
