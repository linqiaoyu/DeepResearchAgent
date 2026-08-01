from __future__ import annotations

import os
import unittest
from datetime import date
from uuid import uuid4

from deepresearch_agent.settings import Settings, project_root
from deepresearch_agent.storage import PostgresStore, StoredChunk
from deepresearch_agent.storage.factory import build_store
from deepresearch_agent.workflow import DeepResearchEngine


_DSN = os.getenv("DEEPRESEARCH_POSTGRES_DSN") or os.getenv("DEEPRESEARCH_PG_DSN")


@unittest.skipUnless(_DSN, "DEEPRESEARCH_POSTGRES_DSN or DEEPRESEARCH_PG_DSN not set")
class PostgresStorageLiveTests(unittest.TestCase):
    def _store(self) -> PostgresStore:
        assert _DSN is not None
        return PostgresStore(_DSN, migrations_dir=project_root() / "migrations")

    def test_document_version_delete_cascades_chunks_without_orphans(self) -> None:
        store = self._store()
        suffix = uuid4().hex
        result = store.record_document_version(
            canonical_url=f"https://example.test/postgres-cascade/{suffix}",
            file_sha256="a" * 64,
            effective_date="2025-12-31",
            chunks=[
                StoredChunk(
                    id=f"postgres-cascade-{suffix}",
                    char_start=0,
                    char_end=8,
                    page_number=1,
                    effective_date="2025-12-31",
                    content="contract",
                )
            ],
        )
        with store._connection() as connection, connection.cursor() as cursor:  # noqa: SLF001
            cursor.execute("DELETE FROM document_version WHERE id = %s", (result.document_version_id,))
            orphan_count = cursor.execute(
                "SELECT count(*) FROM chunk WHERE document_version_id NOT IN "
                "(SELECT id FROM document_version)"
            ).fetchone()[0]
        self.assertEqual(orphan_count, 0)

    def test_postgres_checkpoint_resume_preserves_state(self) -> None:
        assert _DSN is not None
        settings = Settings(
            storage_path=project_root() / "artifacts" / "047" / "postgres-checkpoint.db",
            storage_backend="postgres",
            postgres_dsn=_DSN,
            max_critic_iter=1,
            as_of=date(2026, 1, 1),
        )
        engine = DeepResearchEngine(settings=settings, store=build_store(settings))
        try:
            paused = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
                stop_after_phase="extracting",
            )
            resumed = engine.run(research_id=paused.research_id, resume=True)
        finally:
            engine.close()

        self.assertEqual(paused.status, "paused")
        self.assertGreater(len(paused.evidence_store), 0)
        self.assertEqual(resumed.status, "done")
        self.assertGreaterEqual(len(resumed.evidence_store), len(paused.evidence_store))
