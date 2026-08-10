from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import NAMESPACE_URL, uuid5

from deepresearch_agent.schemas import EvaluationResult, Evidence
from deepresearch_agent.storage.mapping import (
    AS_OF_PREDICATE,
    EVIDENCE_COLUMNS,
    RESOLVED_CHUNK_COLUMNS,
    RESOLVED_CHUNK_JOIN,
    evidence_fields,
    evidence_from_row,
    resolved_chunk_from_row,
    validate_document_version,
)
from deepresearch_agent.storage.protocol import DocumentIngestResult, ResolvedChunk, StoredChunk


class PostgresStore:
    """Postgres implementation of the stable workflow storage contract.

    This deliberately does **not** inherit from ``SQLiteStore``. It used to, and
    the inheritance was a trap: ``__init__`` never called ``super().__init__()``,
    so ``self.path`` did not exist and every SQLite method was one call away
    from ``AttributeError``. It survived only because all eight protocol methods
    happened to be overridden -- meaning any method later added to
    ``SQLiteStore`` would have been silently inherited here and executed SQLite
    SQL against Postgres. Row mapping and precondition checks that genuinely are
    shared now live in ``storage.mapping`` and are imported by both backends.

    The driver is imported lazily so the deterministic SQLite-only CI path does
    not require a running Postgres service. Schema evolution is exclusively
    through the versioned SQL files in ``migrations/``, and
    ``scripts/check_storage_schema_parity.py`` fails when those stop matching
    what ``SQLiteStore`` builds.
    """

    def __init__(self, dsn: str, *, migrations_dir: Path) -> None:
        self.dsn = dsn
        self.migrations_dir = migrations_dir
        self._psycopg = self._load_driver()
        self.apply_migrations()

    @staticmethod
    def _load_driver() -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on optional extra.
            raise RuntimeError(
                "PostgresStore requires psycopg; install the project dev dependencies."
            ) from exc
        return psycopg

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with self._psycopg.connect(self.dsn) as conn:
            yield conn

    def apply_migrations(self) -> int:
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            applied = 0
            for path in sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
                sql = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                row = cursor.execute(
                    "SELECT sha256 FROM schema_migrations WHERE version = %s", (path.name,)
                ).fetchone()
                if row:
                    if row[0] != digest:
                        raise RuntimeError(f"migration digest mismatch: {path.name}")
                    continue
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                    (path.name, digest),
                )
                applied += 1
        return applied

    def add_evidence_many(self, items: list[Evidence]) -> None:
        columns = ("position", *EVIDENCE_COLUMNS)
        placeholders = ", ".join(f"%({name})s" for name in columns)
        assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in columns)
        with self._connection() as conn, conn.cursor() as cursor:
            for position, item in enumerate(items):
                cursor.execute(
                    f"INSERT INTO evidence ({', '.join(columns)}) VALUES ({placeholders}) "
                    f"ON CONFLICT (id) DO UPDATE SET {assignments}",
                    {"position": position, **evidence_fields(item)},
                )

    def list_evidence(self, research_id: str) -> list[Evidence]:
        with self._connection() as conn, conn.cursor(
            row_factory=self._psycopg.rows.dict_row
        ) as cursor:
            rows = cursor.execute(
                "SELECT * FROM evidence WHERE research_id = %s ORDER BY position, id",
                (research_id,),
            ).fetchall()
        return [evidence_from_row(row) for row in rows]

    def save_evaluation(self, result: EvaluationResult) -> None:
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO evaluation_result (research_id, result_json, created_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (research_id) DO UPDATE SET
                    result_json = EXCLUDED.result_json, created_at = EXCLUDED.created_at
                """,
                (result.research_id, result.model_dump_json(), result.created_at),
            )

    def latest_metrics(self) -> list[EvaluationResult]:
        with self._connection() as conn, conn.cursor() as cursor:
            rows = cursor.execute(
                "SELECT result_json FROM evaluation_result ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        return [EvaluationResult.model_validate(row[0]) for row in rows]

    def record_document_version(
        self,
        *,
        canonical_url: str,
        file_sha256: str,
        effective_date: str,
        chunks: list[StoredChunk],
        published_at: str | None = None,
    ) -> DocumentIngestResult:
        published_at = validate_document_version(
            file_sha256=file_sha256,
            effective_date=effective_date,
            chunks=chunks,
            published_at=published_at,
        )
        document_id = str(uuid5(NAMESPACE_URL, canonical_url))
        version_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{file_sha256}"))
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO document (id, canonical_url) VALUES (%s, %s) "
                "ON CONFLICT (canonical_url) DO NOTHING",
                (document_id, canonical_url),
            )
            cursor.execute(
                "SELECT count(*) FROM chunk WHERE document_version_id IN "
                "(SELECT id FROM document_version WHERE document_id = %s AND file_sha256 <> %s) "
                "AND status = 'ready'",
                (document_id, file_sha256),
            )
            superseded = int(cursor.fetchone()[0])
            cursor.execute(
                "UPDATE document_version SET status = 'superseded' "
                "WHERE document_id = %s AND file_sha256 <> %s AND status = 'ready'",
                (document_id, file_sha256),
            )
            cursor.execute(
                "UPDATE chunk SET status = 'superseded' WHERE document_version_id IN "
                "(SELECT id FROM document_version WHERE document_id = %s AND file_sha256 <> %s)",
                (document_id, file_sha256),
            )
            # `filing_date` is the document's disclosure date and the input to
            # the as-of guard. Until R112 the column did not exist here at all.
            cursor.execute(
                "INSERT INTO document_version "
                "(id, document_id, file_sha256, effective_date, filing_date, status) "
                "VALUES (%s, %s, %s, %s, %s, 'ready') "
                "ON CONFLICT (document_id, file_sha256) DO UPDATE SET status = 'ready', "
                "effective_date = EXCLUDED.effective_date, filing_date = EXCLUDED.filing_date",
                (version_id, document_id, file_sha256, effective_date, published_at),
            )
            # Chunks are a rebuildable derived index.  Refresh an unchanged
            # document version too, so a deterministic chunking-policy change
            # cannot leave stale searchable chunks behind.
            cursor.execute("DELETE FROM chunk WHERE document_version_id = %s", (version_id,))
            cursor.executemany(
                "INSERT INTO chunk (id, document_version_id, char_start, char_end, page_number, "
                "effective_date, published_at, status, content, bbox_index_json, entity_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'ready', %s, %s::jsonb, %s)",
                [
                    (
                        chunk.id,
                        version_id,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.page_number,
                        chunk.effective_date,
                        published_at,
                        chunk.content,
                        json.dumps([item.model_dump(mode="json") for item in chunk.bbox_index]),
                        chunk.entity_id,
                    )
                    for chunk in chunks
                ],
            )
            cursor.execute(
                "SELECT count(*) FROM chunk WHERE document_version_id = %s AND status = 'ready'",
                (version_id,),
            )
            active = int(cursor.fetchone()[0])
        return DocumentIngestResult(document_id, version_id, active, superseded)

    def rag_status(self) -> dict[str, int]:
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT count(*) FROM document), "
                "(SELECT count(*) FROM document_version WHERE status = 'ready'), "
                "(SELECT count(*) FROM chunk WHERE status = 'ready'), "
                "(SELECT count(*) FROM chunk WHERE status = 'superseded')"
            )
            row = cursor.fetchone()
        return {
            "documents": int(row[0]),
            "active_versions": int(row[1]),
            "active_chunks": int(row[2]),
            "superseded_chunks": int(row[3]),
        }

    def list_ready_chunks(self, *, as_of: str) -> list[ResolvedChunk]:
        with self._connection() as conn, conn.cursor(
            row_factory=self._psycopg.rows.dict_row
        ) as cursor:
            rows = cursor.execute(
                f"SELECT {RESOLVED_CHUNK_COLUMNS} {RESOLVED_CHUNK_JOIN} "
                f"WHERE {AS_OF_PREDICATE}%s ORDER BY chunk.id",
                (as_of,),
            ).fetchall()
        return [resolved_chunk_from_row(row) for row in rows]

    def resolve_ready_chunks(self, chunk_ids: list[str], *, as_of: str) -> list[ResolvedChunk]:
        if not chunk_ids:
            return []
        with self._connection() as conn, conn.cursor(
            row_factory=self._psycopg.rows.dict_row
        ) as cursor:
            rows = cursor.execute(
                f"SELECT {RESOLVED_CHUNK_COLUMNS} {RESOLVED_CHUNK_JOIN} "
                f"WHERE {AS_OF_PREDICATE}%s AND chunk.id = ANY(%s)",
                (as_of, chunk_ids),
            ).fetchall()
        resolved = {str(row["id"]): resolved_chunk_from_row(row) for row in rows}
        return [resolved[chunk_id] for chunk_id in chunk_ids if chunk_id in resolved]
