from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from deepresearch_agent.schemas import EvaluationResult, Evidence, StructuredDataRecord


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
                    confidence REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    research_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "evidence", "source_kind", "TEXT NOT NULL DEFAULT 'text'")
            self._ensure_column(conn, "evidence", "structured_record_json", "TEXT")

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
                    source_title, source_pub_date, extract_text, structured_record_json, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        item.source_pub_date.isoformat(),
                        item.extract_text,
                        item.structured_record.model_dump_json() if item.structured_record else None,
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
        return [
            Evidence(
                id=row["id"],
                research_id=row["research_id"],
                sub_question_id=row["sub_question_id"],
                claim=row["claim"],
                claim_type=row["claim_type"],
                source_kind=row["source_kind"],
                source_url=row["source_url"],
                source_title=row["source_title"],
                source_pub_date=row["source_pub_date"],
                extract_text=row["extract_text"],
                structured_record=self._structured_record(row["structured_record_json"]),
                confidence=row["confidence"],
            )
            for row in rows
        ]

    def _structured_record(self, value: str | None) -> StructuredDataRecord | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return StructuredDataRecord.model_validate(payload)

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
