from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import NAMESPACE_URL, uuid5

from deepresearch_agent.schemas import EvaluationResult, Evidence
from deepresearch_agent.storage.protocol import MemoryRecord
from deepresearch_agent.storage.mapping import (
    EVIDENCE_COLUMNS,
    AS_OF_PREDICATE,
    RESOLVED_CHUNK_COLUMNS,
    RESOLVED_CHUNK_JOIN,
    evidence_fields,
    evidence_from_row,
    resolved_chunk_from_row,
    validate_document_version,
)
from deepresearch_agent.storage.protocol import (
    DocumentIngestResult,
    ResolvedChunk,
    StoredChunk,
)


# Shared with the LangGraph SQLite checkpointer. WAL mode changes and first-use
# schema setup take database-wide locks for which SQLite's busy handler is not
# consistently invoked; serialize only that initialization boundary.
SQLITE_INITIALIZATION_LOCK = RLock()


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with SQLITE_INITIALIZATION_LOCK:
            self._setup()

    def _connect(self) -> sqlite3.Connection:
        # R096: `isolation_level="IMMEDIATE"` takes the write lock when the
        # transaction opens. Python's default defers it, so a connection that
        # has already read then tries to write is upgrading a shared lock --
        # SQLite answers SQLITE_BUSY immediately for that case rather than
        # invoking the busy handler, so `timeout` and `busy_timeout` do not
        # apply and the caller sees "database is locked". Eight concurrent
        # request-scoped engines hit it in 1 of 12 standalone runs.
        conn = sqlite3.connect(self.path, timeout=30, isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        # Set the busy timeout before the statement that can itself block.
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _setup(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    research_id TEXT NOT NULL,
                    sub_question_id TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    source_kind TEXT NOT NULL DEFAULT 'text',
                    source_url TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_pub_date TEXT NOT NULL,
                    extract_text TEXT NOT NULL,
                    structured_record_json TEXT,
                    numeric_fields_json TEXT,
                    numeric_fields_incomplete INTEGER NOT NULL DEFAULT 0,
                    source_tier TEXT NOT NULL DEFAULT 'unknown',
                    content_truncated INTEGER NOT NULL DEFAULT 0,
                    bbox_json TEXT,
                    retrieval_ref_json TEXT,
                    confidence REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    research_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document (
                    id TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS document_version (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
                    file_sha256 TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    filing_date TEXT NOT NULL DEFAULT '',
                    published_at_source TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('ready', 'superseded')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(document_id, file_sha256)
                );

                CREATE TABLE IF NOT EXISTS memory_record (
                    namespace TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, scope_key, record_id)
                );

                CREATE TABLE IF NOT EXISTS chunk (
                    id TEXT PRIMARY KEY,
                    document_version_id TEXT NOT NULL REFERENCES document_version(id) ON DELETE CASCADE,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    page_number INTEGER,
                    effective_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ready', 'superseded')),
                    content TEXT NOT NULL,
                    bbox_index_json TEXT NOT NULL DEFAULT '[]',
                    entity_id TEXT NOT NULL DEFAULT '',
                    CHECK(char_end > char_start)
                );
                CREATE INDEX IF NOT EXISTS idx_chunk_document_span
                    ON chunk(document_version_id, char_start, char_end);
                CREATE INDEX IF NOT EXISTS idx_chunk_effective_date
                    ON chunk(effective_date);
                """
            )
            self._ensure_column(conn, "evidence", "source_kind", "TEXT NOT NULL DEFAULT 'text'")
            self._ensure_column(conn, "evidence", "structured_record_json", "TEXT")
            self._ensure_column(conn, "evidence", "numeric_fields_json", "TEXT")
            self._ensure_column(
                conn, "evidence", "numeric_fields_incomplete", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(conn, "evidence", "source_tier", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(conn, "evidence", "content_truncated", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "evidence", "bbox_json", "TEXT")
            self._ensure_column(conn, "evidence", "retrieval_ref_json", "TEXT")
            self._ensure_column(conn, "chunk", "bbox_index_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "chunk", "entity_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "chunk", "published_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "document_version", "filing_date", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn, "document_version", "published_at_source", "TEXT NOT NULL DEFAULT ''"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_published_at ON chunk(published_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_entity_id ON chunk(entity_id)")

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        """Add a column once, even when two connections migrate concurrently.

        SQLite has no ``ADD COLUMN IF NOT EXISTS``, so this reads the schema and
        then alters it. Two request-scoped engines opening the same database can
        both observe the column as missing and both issue the ALTER; the loser
        used to surface ``duplicate column name`` as a migration failure. Losing
        that race means the column exists, which is the intended end state.
        """

        if self._has_column(conn, table, column):
            return
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
            if not self._has_column(conn, table, column):
                raise

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(
            row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        )

    def add_evidence_many(self, items: list[Evidence]) -> None:
        with self._connection() as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO evidence ({', '.join(EVIDENCE_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in EVIDENCE_COLUMNS)})",
                [tuple(evidence_fields(item)[name] for name in EVIDENCE_COLUMNS) for item in items],
            )

    def list_evidence(self, research_id: str) -> list[Evidence]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE research_id = ? ORDER BY rowid",
                (research_id,),
            ).fetchall()
        return [evidence_from_row(row) for row in rows]

    def save_evaluation(self, result: EvaluationResult) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO evaluations (research_id, result_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(research_id) DO UPDATE SET
                    result_json=excluded.result_json,
                    created_at=excluded.created_at
                """,
                (result.research_id, result.model_dump_json(), result.created_at.isoformat()),
            )

    def latest_metrics(self) -> list[EvaluationResult]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT result_json FROM evaluations ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        return [EvaluationResult.model_validate_json(row["result_json"]) for row in rows]

    def record_document_version(
        self,
        *,
        canonical_url: str,
        file_sha256: str,
        effective_date: str,
        chunks: list[StoredChunk],
        published_at: str | None = None,
        published_at_source: str = "",
    ) -> DocumentIngestResult:
        published_at = validate_document_version(
            file_sha256=file_sha256,
            effective_date=effective_date,
            chunks=chunks,
            published_at=published_at,
        )
        document_id = str(uuid5(NAMESPACE_URL, canonical_url))
        version_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{file_sha256}"))
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO document (id, canonical_url) VALUES (?, ?)",
                (document_id, canonical_url),
            )
            existing = conn.execute(
                "SELECT id FROM document_version WHERE document_id = ? AND file_sha256 = ?",
                (document_id, file_sha256),
            ).fetchone()
            superseded = conn.execute(
                "SELECT count(*) AS count FROM chunk WHERE document_version_id IN "
                "(SELECT id FROM document_version WHERE document_id = ? AND file_sha256 <> ?) "
                "AND status = 'ready'",
                (document_id, file_sha256),
            ).fetchone()["count"]
            conn.execute(
                "UPDATE document_version SET status = 'superseded' "
                "WHERE document_id = ? AND file_sha256 <> ? AND status = 'ready'",
                (document_id, file_sha256),
            )
            conn.execute(
                "UPDATE chunk SET status = 'superseded' WHERE document_version_id IN "
                "(SELECT id FROM document_version WHERE document_id = ? AND file_sha256 <> ?)",
                (document_id, file_sha256),
            )
            # `filing_date` is the document's disclosure date and the input to
            # the as-of guard. R085 added the column and no write path ever set
            # it, so retrieval fell back to the period end and admitted filings
            # that had not been published yet.
            conn.execute(
                "INSERT INTO document_version "
                "(id, document_id, file_sha256, effective_date, filing_date, "
                "published_at_source, status) VALUES (?, ?, ?, ?, ?, ?, 'ready') "
                "ON CONFLICT(document_id, file_sha256) DO UPDATE SET status = 'ready', "
                "effective_date = excluded.effective_date, filing_date = excluded.filing_date, "
                "published_at_source = excluded.published_at_source",
                (
                    version_id,
                    document_id,
                    file_sha256,
                    effective_date,
                    published_at,
                    published_at_source,
                ),
            )
            # Chunks are a derived index, not immutable source evidence.  A
            # re-ingest of an unchanged document version must therefore refresh
            # its layout when the deterministic chunking policy changes.
            if existing is not None:
                conn.execute("DELETE FROM chunk WHERE document_version_id = ?", (version_id,))
            conn.executemany(
                "INSERT INTO chunk (id, document_version_id, char_start, char_end, page_number, "
                "effective_date, published_at, status, content, bbox_index_json, entity_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)",
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
            active = conn.execute(
                "SELECT count(*) AS count FROM chunk WHERE document_version_id = ? AND status = 'ready'",
                (version_id,),
            ).fetchone()["count"]
        return DocumentIngestResult(
            document_id=document_id,
            document_version_id=version_id,
            active_chunks=int(active),
            superseded_chunks=int(superseded),
        )

    def rag_status(self) -> dict[str, int]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT (SELECT count(*) FROM document) AS documents, "
                "(SELECT count(*) FROM document_version WHERE status = 'ready') AS active_versions, "
                "(SELECT count(*) FROM chunk WHERE status = 'ready') AS active_chunks, "
                "(SELECT count(*) FROM chunk WHERE status = 'superseded') AS superseded_chunks"
            ).fetchone()
        return {key: int(row[key]) for key in row.keys()}

    def list_ready_chunks(self, *, as_of: str) -> list[ResolvedChunk]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {RESOLVED_CHUNK_COLUMNS} {RESOLVED_CHUNK_JOIN} "
                f"WHERE {AS_OF_PREDICATE}? "
                "ORDER BY chunk.id",
                (as_of,),
            ).fetchall()
        return [resolved_chunk_from_row(row) for row in rows]

    def resolve_ready_chunks(self, chunk_ids: list[str], *, as_of: str) -> list[ResolvedChunk]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {RESOLVED_CHUNK_COLUMNS} {RESOLVED_CHUNK_JOIN} "
                f"WHERE {AS_OF_PREDICATE}? "
                f"AND chunk.id IN ({placeholders})",
                (as_of, *chunk_ids),
            ).fetchall()
        resolved = {str(row["id"]): resolved_chunk_from_row(row) for row in rows}
        return [resolved[chunk_id] for chunk_id in chunk_ids if chunk_id in resolved]

    def write_memory_record(self, record: MemoryRecord) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO memory_record "
                "(namespace, scope_key, record_id, payload, created_at) "
                "VALUES (?, ?, ?, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP)) "
                "ON CONFLICT (namespace, scope_key, record_id) DO UPDATE SET "
                "payload = excluded.payload",
                (
                    record.namespace,
                    record.scope_key,
                    record.record_id,
                    record.payload,
                    record.created_at,
                ),
            )

    def list_memory_records(self, namespace: str, scope_key: str) -> list[MemoryRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT namespace, scope_key, record_id, payload, created_at "
                "FROM memory_record WHERE namespace = ? AND scope_key = ? "
                "ORDER BY record_id",
                (namespace, scope_key),
            ).fetchall()
        return [
            MemoryRecord(
                namespace=str(row["namespace"]),
                scope_key=str(row["scope_key"]),
                record_id=str(row["record_id"]),
                payload=str(row["payload"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]
