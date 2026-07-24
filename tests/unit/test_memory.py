from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from deepresearch_agent.memory import (
    ContextWorkingMemory,
    EpisodicMemory,
    EpisodicQuery,
    EpisodicRecord,
    MemoryStore,
    SemanticFact,
    SemanticMemory,
    SemanticQuery,
    WorkingMemoryQuery,
    WorkingMemoryWrite,
)
from deepresearch_agent.provenance import RunManifest
from deepresearch_agent.research_snapshot import ResearchSnapshot
from deepresearch_agent.schemas import (
    ComparisonTable,
    Evidence,
    EventTimeline,
    RiskMatrix,
    StructuredResearchOutput,
)


def _manifest(run_id: str) -> RunManifest:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    return RunManifest(
        run_id=run_id,
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
        cost_cny_total=0.0,
    )


def _snapshot(as_of: date, manifest_ref: str) -> ResearchSnapshot:
    return ResearchSnapshot(
        question_id="q-1",
        question="宁德时代研究",
        as_of=as_of,
        claims=[],
        structured_objects=StructuredResearchOutput(
            comparison_table=ComparisonTable(question="q"),
            event_timeline=EventTimeline(question="q"),
            risk_matrix=RiskMatrix(question="q"),
        ),
        manifest_ref=manifest_ref,
        manifest=_manifest(manifest_ref),
        flags={},
    )


def _evidence(item_id: str) -> Evidence:
    return Evidence(
        id=item_id,
        research_id="run",
        sub_question_id="sq",
        claim=f"AI Agent evidence {item_id}",
        claim_type="fact",
        source_url=f"https://example.com/{item_id}",
        source_title=item_id,
        source_pub_date=date(2026, 7, 1),
        extract_text=f"AI Agent evidence {item_id}",
        confidence=0.8,
    )


class MemoryStoreTest(unittest.TestCase):
    def test_episodic_memory_uses_snapshot_key_and_is_deterministic(self) -> None:
        memory = EpisodicMemory()
        self.assertIsInstance(memory, MemoryStore)
        later = EpisodicRecord(
            snapshot=_snapshot(date(2026, 7, 24), "later"),
            trajectory_ref="runs/later/trajectory.json",
        )
        earlier = EpisodicRecord(
            snapshot=_snapshot(date(2026, 7, 9), "earlier"),
            trajectory_ref="runs/earlier/trajectory.json",
        )
        memory.write(later)
        memory.write(earlier)

        first = memory.query(EpisodicQuery(question_id="q-1"))
        second = memory.query(EpisodicQuery(question_id="q-1"))

        self.assertEqual(first, second)
        self.assertEqual(
            [item.snapshot.as_of for item in first],
            [date(2026, 7, 9), date(2026, 7, 24)],
        )
        exact = memory.query(
            EpisodicQuery(
                question_id="q-1",
                as_of=date(2026, 7, 24),
            )
        )
        self.assertEqual(exact, [later])

    def test_semantic_subset_query_returns_full_time_series(self) -> None:
        memory = SemanticMemory()
        facts = [
            SemanticFact(
                entity="宁德时代",
                normalized_metric="归母净利润",
                period="2024Q3",
                scope="单季",
                value=10.0,
                unit="亿元",
                source_urls=["https://example.com/q3-old"],
                as_of=date(2024, 10, 1),
                confidence=0.8,
            ),
            SemanticFact(
                entity="宁德时代",
                normalized_metric="归母净利润",
                period="2024Q3",
                scope="单季",
                value=11.0,
                unit="亿元",
                source_urls=["https://example.com/q3-new"],
                as_of=date(2024, 10, 20),
                confidence=0.9,
            ),
            SemanticFact(
                entity="宁德时代",
                normalized_metric="归母净利润",
                period="2024Q3",
                scope="前三季累计",
                value=30.0,
                unit="亿元",
                source_urls=["https://example.com/ytd"],
                as_of=date(2024, 10, 20),
                confidence=0.95,
            ),
        ]
        for fact in reversed(facts):
            memory.write(fact)

        first = memory.query(
            SemanticQuery(
                entity="宁德时代",
                normalized_metric="归母净利润",
            )
        )
        second = memory.query(
            SemanticQuery(
                entity="宁德时代",
                normalized_metric="归母净利润",
            )
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        single = next(item for item in first if item.scope == "单季")
        cumulative = next(
            item for item in first if item.scope == "前三季累计"
        )
        self.assertEqual(
            [item.value for item in single.observations],
            [10.0, 11.0],
        )
        self.assertEqual(
            [item.value for item in cumulative.observations],
            [30.0],
        )

    def test_semantic_query_supports_any_four_key_subset(self) -> None:
        memory = SemanticMemory()
        memory.write(
            SemanticFact(
                entity="宁德时代",
                normalized_metric="营收",
                period="2024",
                scope="全年",
                value=100,
                as_of=date(2025, 1, 1),
                confidence=0.9,
            )
        )
        memory.write(
            SemanticFact(
                entity="比亚迪",
                normalized_metric="营收",
                period="2024",
                scope="全年",
                value=120,
                as_of=date(2025, 1, 1),
                confidence=0.9,
            )
        )

        by_period_scope = memory.query(
            SemanticQuery(period="2024", scope="全年")
        )
        by_entity = memory.query(SemanticQuery(entity="比亚迪"))

        self.assertEqual(len(by_period_scope), 2)
        self.assertEqual([item.entity for item in by_entity], ["比亚迪"])

    def test_working_memory_adapts_context_packer_deterministically(self) -> None:
        memory = ContextWorkingMemory()
        memory.write(
            WorkingMemoryWrite(
                research_id="run",
                evidence=[_evidence("a"), _evidence("b")],
            )
        )
        query = WorkingMemoryQuery(
            research_id="run",
            topic="AI Agent",
            budget=200,
            as_of=date(2026, 7, 24),
        )

        self.assertEqual(
            memory.query(query).model_dump(),
            memory.query(query).model_dump(),
        )
        empty = memory.query(
            WorkingMemoryQuery(
                research_id="missing",
                topic="AI Agent",
                budget=200,
            )
        )
        self.assertEqual(empty.selected, [])
        self.assertEqual(memory.lifecycle, "run")


if __name__ == "__main__":
    unittest.main()
