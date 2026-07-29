from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from deepresearch_agent.schemas import (
    BoundingBox,
    EvaluationResult,
    Evidence,
    NumericFields,
    RetrievalReference,
    StructuredDataRecord,
)
from deepresearch_agent.storage.protocol import (
    DocumentIngestResult,
    ResolvedChunk,
    StoredChunk,
)


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
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
                    status TEXT NOT NULL CHECK(status IN ('ready', 'superseded')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(document_id, file_sha256)
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
            self._ensure_column(conn, "evidence", "numeric_fields_incomplete", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "evidence", "source_tier", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(conn, "evidence", "content_truncated", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "evidence", "bbox_json", "TEXT")
            self._ensure_column(conn, "evidence", "retrieval_ref_json", "TEXT")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add_evidence_many(self, items: list[Evidence]) -> None:
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO evidence (
                    id, research_id, sub_question_id, claim, claim_type, source_kind, source_url,
                    source_title, source_pub_date, extract_text, structured_record_json,
                    numeric_fields_json, numeric_fields_incomplete, source_tier,
                    content_truncated, bbox_json, retrieval_ref_json, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.research_id,
                        item.sub_question_id,
                        item.claim,
                        item.claim_type,
                        item.source_kind,
                        item.source_url,
                        item.source_title,
                        item.source_pub_date.isoformat() if item.source_pub_date else "unknown",
                        item.extract_text,
                        item.structured_record.model_dump_json() if item.structured_record else None,
                        item.numeric_fields.model_dump_json() if item.numeric_fields else None,
                        int(item.numeric_fields_incomplete),
                        item.source_tier,
                        int(item.content_truncated),
                        item.bbox.model_dump_json() if item.bbox else None,
                        item.retrieval_ref.model_dump_json() if item.retrieval_ref else None,
                        item.confidence,
                    )
                    for item in items
                ],
            )

    def list_evidence(self, research_id: str) -> list[Evidence]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE research_id = ? ORDER BY rowid",
                (research_id,),
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def _evidence_from_row(self, row: Mapping[str, object]) -> Evidence:
        source_pub_date = row["source_pub_date"]
        return Evidence(
            id=str(row["id"]),
            research_id=str(row["research_id"]),
            sub_question_id=str(row["sub_question_id"]),
            claim=str(row["claim"]),
            claim_type=str(row["claim_type"]),
            source_kind=str(row["source_kind"]),
            source_url=str(row["source_url"]),
            source_title=str(row["source_title"]),
            source_pub_date=None if source_pub_date in {None, "unknown"} else str(source_pub_date),
            extract_text=str(row["extract_text"]),
            structured_record=self._structured_record(_as_json_text(row["structured_record_json"])),
            numeric_fields=self._numeric_fields(_as_json_text(row["numeric_fields_json"])),
            numeric_fields_incomplete=bool(row["numeric_fields_incomplete"]),
            source_tier=str(row["source_tier"]),
            content_truncated=bool(row["content_truncated"]),
            bbox=self._bbox(_as_json_text(row["bbox_json"])),
            retrieval_ref=self._retrieval_ref(_as_json_text(row["retrieval_ref_json"])),
            confidence=float(row["confidence"]),
        )

    def _structured_record(self, value: str | None) -> StructuredDataRecord | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return StructuredDataRecord.model_validate(payload)

    def _numeric_fields(self, value: str | None) -> NumericFields | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return NumericFields.model_validate(payload)

    def _bbox(self, value: str | None) -> BoundingBox | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return BoundingBox.model_validate(payload)

    def _retrieval_ref(self, value: str | None) -> RetrievalReference | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return RetrievalReference.model_validate(payload)

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
    ) -> DocumentIngestResult:
        if not chunks:
            raise ValueError("document version must contain at least one located chunk")
        if any(chunk.effective_date != effective_date for chunk in chunks):
            raise ValueError("every chunk must use the document effective_date")
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
            conn.execute(
                "INSERT INTO document_version (id, document_id, file_sha256, effective_date, status) "
                "VALUES (?, ?, ?, ?, 'ready') "
                "ON CONFLICT(document_id, file_sha256) DO UPDATE SET status = 'ready', "
                "effective_date = excluded.effective_date",
                (version_id, document_id, file_sha256, effective_date),
            )
            # Chunks are a derived index, not immutable source evidence.  A
            # re-ingest of an unchanged document version must therefore refresh
            # its layout when the deterministic chunking policy changes.
            if existing is not None:
                conn.execute("DELETE FROM chunk WHERE document_version_id = ?", (version_id,))
            conn.executemany(
                "INSERT INTO chunk (id, document_version_id, char_start, char_end, page_number, "
                "effective_date, status, content) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?)",
                [
                    (
                        chunk.id,
                        version_id,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.page_number,
                        chunk.effective_date,
                        chunk.content,
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
                "SELECT chunk.id, chunk.document_version_id, document.canonical_url, chunk.char_start, "
                "chunk.char_end, chunk.page_number, chunk.effective_date, chunk.content "
                "FROM chunk JOIN document_version ON document_version.id = chunk.document_version_id "
                "JOIN document ON document.id = document_version.document_id "
                "WHERE chunk.status = 'ready' AND chunk.effective_date <= ? "
                "ORDER BY chunk.id",
                (as_of,),
            ).fetchall()
        return [self._resolved_chunk_from_row(row) for row in rows]

    def resolve_ready_chunks(self, chunk_ids: list[str], *, as_of: str) -> list[ResolvedChunk]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT chunk.id, chunk.document_version_id, document.canonical_url, chunk.char_start, "
                "chunk.char_end, chunk.page_number, chunk.effective_date, chunk.content "
                "FROM chunk JOIN document_version ON document_version.id = chunk.document_version_id "
                "JOIN document ON document.id = document_version.document_id "
                f"WHERE chunk.status = 'ready' AND chunk.effective_date <= ? AND chunk.id IN ({placeholders})",
                (as_of, *chunk_ids),
            ).fetchall()
        resolved = {str(row["id"]): self._resolved_chunk_from_row(row) for row in rows}
        return [resolved[chunk_id] for chunk_id in chunk_ids if chunk_id in resolved]

    @staticmethod
    def _resolved_chunk_from_row(row: Mapping[str, object]) -> ResolvedChunk:
        return ResolvedChunk(
            id=str(row["id"]),
            document_version_id=str(row["document_version_id"]),
            canonical_url=str(row["canonical_url"]),
            char_start=int(row["char_start"]),
            char_end=int(row["char_end"]),
            page_number=None if row["page_number"] is None else int(row["page_number"]),
            effective_date=str(row["effective_date"]),
            content=str(row["content"]),
        )


def _as_json_text(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
