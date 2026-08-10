from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.rag.search import RagSearchService, RetrievalFilter, SearchChunk
from deepresearch_agent.schemas import ResearchPlan, SubQuestion
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore, StoredChunk
from deepresearch_agent.tools import ToolErrorKind, ToolExecutionError
from deepresearch_agent.trajectory import load_trajectory
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


class _StaticBackend:
    def __init__(self, chunks: list[SearchChunk]) -> None:
        self.chunks = chunks

    def search(
        self, *, query: str, filters: RetrievalFilter, limit: int
    ) -> list[SearchChunk]:
        del query, filters
        return self.chunks[:limit]


class _FailingReranker:
    def rerank(self, *_args: object, **_kwargs: object) -> object:
        raise ToolExecutionError(ToolErrorKind.TIMEOUT, "recorded rerank timeout")


class _FixedPlanner:
    last_stats: dict[str, object] = {}

    def plan(
        self, topic: str, depth_level: int = 2, research_id: str | None = None
    ) -> ResearchPlan:
        del research_id
        return ResearchPlan(
            topic=topic,
            depth_level=depth_level,
            sub_questions=[
                SubQuestion(
                    id="revenue",
                    question="公司收入是多少？",
                    search_queries=["公司收入"],
                )
            ],
        )


class RagDegradedReplayTest(unittest.TestCase):
    def test_strict_replay_uses_snapshot_and_preserves_degraded_top_n(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "rag-snapshot.db"
            store = SQLiteStore(snapshot)
            content = "公司收入为100亿元，此处是可由权威快照水合的原始披露片段。"
            stored = StoredChunk(
                id="chunk-1",
                char_start=0,
                char_end=len(content),
                page_number=None,
                effective_date="2025-12-31",
                content=content,
                published_at="2025-12-31",
            )
            store.record_document_version(
                canonical_url="https://example.test/report.html",
                file_sha256="a" * 64,
                effective_date="2025-12-31",
                published_at="2025-12-31",
                chunks=[stored],
            )
            chunk = SearchChunk(
                chunk_id=stored.id,
                text=content,
                effective_date=date(2025, 12, 31),
                document_version_id=store.list_ready_chunks(as_of="2025-12-31")[0].document_version_id,
                char_start=0,
                char_end=len(content),
                source_url="https://example.test/report.html",
                published_at=date(2025, 12, 31),
            )
            rag = RagSearchService(
                lexical=_StaticBackend([chunk]),
                dense=_StaticBackend([]),
                reranker=_FailingReranker(),
                retrieval_top_k=50,
                rerank_top_n=8,
                rerank_enabled=True,
                rerank_fail_open=True,
                index_version="replay-index-v1",
            )
            settings = Settings(
                storage_path=root / "workflow.db",
                runs_root=root / "runs",
                llm_ledger_path=root / "ledger.jsonl",
                as_of=date(2026, 1, 1),
                rag_enabled=True,
                injection_guard_enabled=True,
                dynamic_capability_enabled=False,
                trajectory_record_enabled=True,
                structured_logging_enabled=False,
                run_manifest_enabled=True,
                config_fail_fast_enabled=False,
            )
            engine = DeepResearchEngine(settings=settings, rag_search=rag)
            engine.planner = _FixedPlanner()
            state = engine.run(topic="公司收入", depth_level=1)
            engine._checkpoint_conn.close()
            manifest = json.loads(
                (root / "runs" / state.research_id / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            trajectory = load_trajectory(
                root / "runs" / state.research_id / "trajectory.json"
            )

            missing_snapshot = replay_trajectory(trajectory, mode="strict")
            replay = replay_trajectory(
                trajectory,
                mode="strict",
                rag_snapshot=snapshot,
            )

        self.assertEqual(missing_snapshot.status, "cache_miss")
        self.assertIn("snapshot is required", missing_snapshot.cache_miss or "")
        self.assertEqual(replay.status, "reproduced", replay.cache_miss)
        calls = [
            call
            for call in trajectory.tool_calls
            if call.tool_spec.get("name") == "rag_search"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].result["rerank_status"], "degraded")
        self.assertEqual(calls[0].result["candidate_ids"], ["chunk-1"])
        self.assertTrue(
            any(
                event["tool"] == "rerank" and event["reason"] == "timeout"
                for event in manifest["degradation_events"]
            )
        )


if __name__ == "__main__":
    unittest.main()
