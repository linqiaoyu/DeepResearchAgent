from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import EvaluationResult, Evidence, RetrievalReference
from deepresearch_agent.storage import PostgresStore, SQLiteStore, StorageProtocol
from deepresearch_agent.settings import project_root


def _evidence(identifier: str, research_id: str) -> Evidence:
    return Evidence(
        id=identifier,
        research_id=research_id,
        sub_question_id="q1",
        claim="contract evidence",
        claim_type="fact",
        source_url="https://example.test/source",
        source_title="source",
        source_pub_date=date(2026, 1, 2),
        extract_text="contract text",
        retrieval_ref=RetrievalReference(
            chunk_id="chunk-1",
            document_version_id="version-1",
            index_version="index-1",
            char_start=0,
            char_end=13,
        ),
    )


class StorageContractTests(unittest.TestCase):
    def _assert_evidence_contract(self, store: StorageProtocol) -> None:
        store.add_evidence_many([_evidence("second", "run"), _evidence("first", "run")])
        restored = store.list_evidence("run")
        self.assertEqual([item.id for item in restored], ["second", "first"])
        self.assertEqual(restored[0].source_pub_date, date(2026, 1, 2))
        self.assertEqual(restored[0].retrieval_ref.chunk_id, "chunk-1")
        store.save_evaluation(
            EvaluationResult(
                research_id="run",
                task_success_rate=1.0,
                critic_catch_rate=1.0,
                latency_seconds=0.0,
            )
        )
        self.assertEqual(store.latest_metrics()[0].research_id, "run")

    def test_sqlite_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._assert_evidence_contract(SQLiteStore(Path(directory) / "store.db"))

    @unittest.skipUnless(
        os.getenv("DEEPRESEARCH_POSTGRES_DSN") or os.getenv("DEEPRESEARCH_PG_DSN"),
        "DEEPRESEARCH_POSTGRES_DSN or DEEPRESEARCH_PG_DSN not set",
    )
    def test_postgres_contract_and_idempotent_migration(self) -> None:
        store = PostgresStore(
            os.getenv("DEEPRESEARCH_POSTGRES_DSN") or os.environ["DEEPRESEARCH_PG_DSN"],
            migrations_dir=project_root() / "migrations",
        )
        self.assertEqual(store.apply_migrations(), 0)
        self._assert_evidence_contract(store)


if __name__ == "__main__":
    unittest.main()
