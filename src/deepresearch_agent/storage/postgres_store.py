from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import NAMESPACE_URL, uuid5

from deepresearch_agent.schemas import EvaluationResult, Evidence, TextBoundingBox
from deepresearch_agent.storage.sqlite_store import SQLiteStore
from deepresearch_agent.storage.protocol import DocumentIngestResult, ResolvedChunk, StoredChunk


class PostgresStore(SQLiteStore):
    """Postgres implementation of the stable workflow storage contract.

    The driver is imported lazily so the deterministic SQLite-only CI path does
    not require a running Postgres service.  Schema evolution is exclusively
    through the versioned SQL files in ``migrations/``.
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
        with self._connection() as conn, conn.cursor() as cursor:
            for position, item in enumerate(items):
                cursor.execute(
                    """
                    INSERT INTO evidence (
                        id, research_id, position, sub_question_id, claim, claim_type,
                        source_kind, source_url, source_title, source_pub_date,
                        extract_text, structured_record_json, numeric_fields_json,
                        numeric_fields_incomplete, source_tier, content_truncated,
                        bbox_json, retrieval_ref_json, confidence
                    ) VALUES (
                        %(id)s, %(research_id)s, %(position)s, %(sub_question_id)s,
                        %(claim)s, %(claim_type)s, %(source_kind)s, %(source_url)s,
                        %(source_title)s, %(source_pub_date)s, %(extract_text)s,
                        %(structured_record_json)s, %(numeric_fields_json)s,
                        %(numeric_fields_incomplete)s, %(source_tier)s,
                        %(content_truncated)s, %(bbox_json)s, %(retrieval_ref_json)s, %(confidence)s
                    ) ON CONFLICT (id) DO UPDATE SET
                        research_id = EXCLUDED.research_id, position = EXCLUDED.position,
                        sub_question_id = EXCLUDED.sub_question_id, claim = EXCLUDED.claim,
                        claim_type = EXCLUDED.claim_type, source_kind = EXCLUDED.source_kind,
                        source_url = EXCLUDED.source_url, source_title = EXCLUDED.source_title,
                        source_pub_date = EXCLUDED.source_pub_date, extract_text = EXCLUDED.extract_text,
                        structured_record_json = EXCLUDED.structured_record_json,
                        numeric_fields_json = EXCLUDED.numeric_fields_json,
                        numeric_fields_incomplete = EXCLUDED.numeric_fields_incomplete,
                        source_tier = EXCLUDED.source_tier, content_truncated = EXCLUDED.content_truncated,
                        bbox_json = EXCLUDED.bbox_json,
                        retrieval_ref_json = EXCLUDED.retrieval_ref_json,
                        confidence = EXCLUDED.confidence
                    """,
                    _evidence_row(item, position),
                )

    def list_evidence(self, research_id: str) -> list[Evidence]:
        with self._connection() as conn, conn.cursor(row_factory=self._psycopg.rows.dict_row) as cursor:
            rows = cursor.execute(
                "SELECT * FROM evidence WHERE research_id = %s ORDER BY position, id", (research_id,)
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

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
    ) -> DocumentIngestResult:
        if not chunks:
            raise ValueError("document version must contain at least one located chunk")
        if any(chunk.char_start < 0 or chunk.char_end <= chunk.char_start for chunk in chunks):
            raise ValueError("chunk character ranges must be non-empty and non-negative")
        if any(chunk.page_number is not None and chunk.page_number < 1 for chunk in chunks):
            raise ValueError("chunk page numbers must be positive when present")
        if any(chunk.effective_date != effective_date for chunk in chunks):
            raise ValueError("every chunk must use the document effective_date")
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
            cursor.execute(
                "INSERT INTO document_version (id, document_id, file_sha256, effective_date, status) "
                "VALUES (%s, %s, %s, %s, 'ready') "
                "ON CONFLICT (document_id, file_sha256) DO UPDATE SET status = 'ready', "
                "effective_date = EXCLUDED.effective_date",
                (version_id, document_id, file_sha256, effective_date),
            )
            # Chunks are a rebuildable derived index.  Refresh an unchanged
            # document version too, so a deterministic chunking-policy change
            # cannot leave stale searchable chunks behind.
            cursor.execute("DELETE FROM chunk WHERE document_version_id = %s", (version_id,))
            cursor.executemany(
                "INSERT INTO chunk (id, document_version_id, char_start, char_end, page_number, "
                "effective_date, status, content, bbox_index_json) VALUES (%s, %s, %s, %s, %s, %s, 'ready', %s, %s::jsonb)",
                [
                    (
                        chunk.id,
                        version_id,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.page_number,
                        chunk.effective_date,
                        chunk.content,
                        json.dumps([item.model_dump(mode="json") for item in chunk.bbox_index]),
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
        with self._connection() as conn, conn.cursor(row_factory=self._psycopg.rows.dict_row) as cursor:
            rows = cursor.execute(
                "SELECT chunk.id, chunk.document_version_id, document.canonical_url, chunk.char_start, "
                "chunk.char_end, chunk.page_number, chunk.effective_date, chunk.content, chunk.bbox_index_json "
                "FROM chunk JOIN document_version ON document_version.id = chunk.document_version_id "
                "JOIN document ON document.id = document_version.document_id "
                "WHERE chunk.status = 'ready' AND chunk.effective_date <= %s ORDER BY chunk.id",
                (as_of,),
            ).fetchall()
        return [self._resolved_chunk_from_row(row) for row in rows]

    def resolve_ready_chunks(self, chunk_ids: list[str], *, as_of: str) -> list[ResolvedChunk]:
        if not chunk_ids:
            return []
        with self._connection() as conn, conn.cursor(row_factory=self._psycopg.rows.dict_row) as cursor:
            rows = cursor.execute(
                "SELECT chunk.id, chunk.document_version_id, document.canonical_url, chunk.char_start, "
                "chunk.char_end, chunk.page_number, chunk.effective_date, chunk.content, chunk.bbox_index_json "
                "FROM chunk JOIN document_version ON document_version.id = chunk.document_version_id "
                "JOIN document ON document.id = document_version.document_id "
                "WHERE chunk.status = 'ready' AND chunk.effective_date <= %s AND chunk.id = ANY(%s)",
                (as_of, chunk_ids),
            ).fetchall()
        resolved = {str(row["id"]): self._resolved_chunk_from_row(row) for row in rows}
        return [resolved[chunk_id] for chunk_id in chunk_ids if chunk_id in resolved]

    @staticmethod
    def _resolved_chunk_from_row(row: dict[str, object]) -> ResolvedChunk:
        bbox_value = row["bbox_index_json"]
        if isinstance(bbox_value, str):
            bbox_items = json.loads(bbox_value)
        else:
            bbox_items = bbox_value
        if not isinstance(bbox_items, list):
            raise ValueError("chunk bbox_index_json must be a list")
        return ResolvedChunk(
            id=str(row["id"]),
            document_version_id=str(row["document_version_id"]),
            canonical_url=str(row["canonical_url"]),
            char_start=int(row["char_start"]),
            char_end=int(row["char_end"]),
            page_number=None if row["page_number"] is None else int(row["page_number"]),
            effective_date=str(row["effective_date"]),
            content=str(row["content"]),
            bbox_index=tuple(TextBoundingBox.model_validate(item) for item in bbox_items),
        )


def _evidence_row(item: Evidence, position: int) -> dict[str, object]:
    return {
        "id": item.id,
        "research_id": item.research_id,
        "position": position,
        "sub_question_id": item.sub_question_id,
        "claim": item.claim,
        "claim_type": item.claim_type,
        "source_kind": item.source_kind,
        "source_url": item.source_url,
        "source_title": item.source_title,
        "source_pub_date": item.source_pub_date,
        "extract_text": item.extract_text,
        "structured_record_json": item.structured_record.model_dump_json() if item.structured_record else None,
        "numeric_fields_json": item.numeric_fields.model_dump_json() if item.numeric_fields else None,
        "numeric_fields_incomplete": item.numeric_fields_incomplete,
        "source_tier": item.source_tier,
        "content_truncated": item.content_truncated,
        "bbox_json": item.bbox.model_dump_json() if item.bbox else None,
        "retrieval_ref_json": item.retrieval_ref.model_dump_json() if item.retrieval_ref else None,
        "confidence": item.confidence,
    }
