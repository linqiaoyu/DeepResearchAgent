from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from deepresearch_agent.schemas import EvaluationResult, Evidence, RetrievalReference
from deepresearch_agent.storage import (
    MemoryRecord,
    PostgresStore,
    SQLiteStore,
    StorageProtocol,
    StoredChunk,
)
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
    """One contract, asserted identically against every backend.

    R112 found this suite covered four of the eight protocol methods, and that
    the drift between the backends was in the four it did not reach: Postgres
    returned an empty ``filing_date`` because its schema had no such column, and
    accepted a malformed ``file_sha256`` that SQLite refused. Both backends now
    answer the same assertions for every method on ``StorageProtocol``.
    """

    def _assert_memory_contract(self, store: StorageProtocol) -> None:
        """R122: cross-run memory, asserted identically on every backend."""

        self.assertEqual(store.list_memory_records("procedural", "财报解读"), [])
        store.write_memory_record(
            MemoryRecord(
                namespace="procedural",
                scope_key="财报解读",
                record_id="run-b|sq1|0",
                payload='{"strategy": "b"}',
            )
        )
        store.write_memory_record(
            MemoryRecord(
                namespace="procedural",
                scope_key="财报解读",
                record_id="run-a|sq1|0",
                payload='{"strategy": "a"}',
            )
        )
        rows = store.list_memory_records("procedural", "财报解读")
        self.assertEqual([row.record_id for row in rows], ["run-a|sq1|0", "run-b|sq1|0"])
        self.assertEqual(rows[0].payload, '{"strategy": "a"}')

        # Re-writing the same key replaces the payload rather than duplicating.
        store.write_memory_record(
            MemoryRecord(
                namespace="procedural",
                scope_key="财报解读",
                record_id="run-a|sq1|0",
                payload='{"strategy": "a2"}',
            )
        )
        rows = store.list_memory_records("procedural", "财报解读")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload, '{"strategy": "a2"}')

        # Namespaces and scope keys are separate drawers.
        store.write_memory_record(
            MemoryRecord(
                namespace="episodic",
                scope_key="财报解读",
                record_id="2026-07-09|m1",
                payload='{"kind": "episodic"}',
            )
        )
        self.assertEqual(len(store.list_memory_records("procedural", "财报解读")), 2)
        self.assertEqual(len(store.list_memory_records("episodic", "财报解读")), 1)
        self.assertEqual(store.list_memory_records("procedural", "对比研究"), [])

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

    def _assert_document_contract(self, store: StorageProtocol) -> None:
        suffix = uuid4().hex
        url = f"https://example.test/contract/{suffix}"
        chunk_id = f"contract-chunk-{suffix}"
        # A 20-F for FY2025 is not disclosed until well into 2026. The gap
        # between the two dates is the entire point of storing both.
        effective_date = "2025-12-31"
        filing_date = "2026-03-20"
        result = store.record_document_version(
            canonical_url=url,
            file_sha256="b" * 64,
            effective_date=effective_date,
            published_at=filing_date,
            published_at_source="exchange_registry",
            chunks=[
                StoredChunk(
                    id=chunk_id,
                    char_start=0,
                    char_end=8,
                    page_number=1,
                    effective_date=effective_date,
                    published_at=filing_date,
                    published_at_source="exchange_registry",
                    content="contract",
                    entity_id="contractco",
                )
            ],
        )
        self.assertEqual(result.active_chunks, 1)

        status = store.rag_status()
        self.assertGreaterEqual(status["documents"], 1)
        self.assertGreaterEqual(status["active_chunks"], 1)

        listed = {chunk.id: chunk for chunk in store.list_ready_chunks(as_of="9999-12-31")}
        self.assertIn(chunk_id, listed)
        stored = listed[chunk_id]
        self.assertEqual(stored.canonical_url, url)
        self.assertEqual(stored.effective_date, effective_date)
        self.assertEqual(stored.entity_id, "contractco")
        # The disclosure date must survive the round trip. Postgres returned ""
        # here for 27 rounds, which silently degraded the as-of guard to the
        # period end and admitted filings that were not yet public.
        self.assertEqual(stored.filing_date, filing_date)
        self.assertEqual(stored.published_at, filing_date)
        self.assertEqual(stored.published_at_source, "exchange_registry")

        resolved = store.resolve_ready_chunks([chunk_id], as_of="9999-12-31")
        self.assertEqual([chunk.id for chunk in resolved], [chunk_id])
        self.assertEqual(resolved[0].filing_date, filing_date)
        self.assertEqual(resolved[0].published_at_source, "exchange_registry")
        self.assertEqual(resolved[0].content, "contract")

        # A chunk is invisible before it was disclosed, not before its period
        # ended: as-of the day after the period end it must still be hidden.
        self.assertEqual(store.resolve_ready_chunks([chunk_id], as_of="2026-01-01"), [])
        self.assertNotIn(
            chunk_id, {chunk.id for chunk in store.list_ready_chunks(as_of="2026-01-01")}
        )
        self.assertEqual(store.resolve_ready_chunks([], as_of="9999-12-31"), [])

    def _assert_rejects_invalid_documents(self, store: StorageProtocol) -> None:
        chunk = StoredChunk(
            id=f"reject-{uuid4().hex}",
            char_start=0,
            char_end=4,
            page_number=1,
            effective_date="2025-12-31",
            content="text",
        )
        with self.assertRaises(ValueError):
            store.record_document_version(
                canonical_url="https://example.test/reject",
                file_sha256="not-a-digest",
                effective_date="2025-12-31",
                chunks=[chunk],
            )
        with self.assertRaises(ValueError):
            store.record_document_version(
                canonical_url="https://example.test/reject",
                file_sha256="c" * 64,
                effective_date="2025-12-31",
                chunks=[],
            )

    def _assert_full_contract(self, store: StorageProtocol) -> None:
        self._assert_evidence_contract(store)
        self._assert_document_contract(store)
        self._assert_rejects_invalid_documents(store)
        self._assert_memory_contract(store)

    def test_sqlite_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._assert_full_contract(SQLiteStore(Path(directory) / "store.db"))

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
        self._assert_full_contract(store)


if __name__ == "__main__":
    unittest.main()
