from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from deepresearch_agent.schemas import EvaluationResult, Evidence, ResearchState, utc_now


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
                CREATE TABLE IF NOT EXISTS checkpoints (
                    research_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    research_id TEXT NOT NULL,
                    sub_question_id TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_pub_date TEXT NOT NULL,
                    extract_text TEXT NOT NULL,
                    confidence REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    research_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_checkpoint(self, state: ResearchState) -> None:
        state.updated_at = utc_now()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (research_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(research_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (state.research_id, state.model_dump_json(), state.updated_at.isoformat()),
            )

    def load_checkpoint(self, research_id: str) -> ResearchState | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM checkpoints WHERE research_id = ?",
                (research_id,),
            ).fetchone()
        if not row:
            return None
        return ResearchState.model_validate_json(row["state_json"])

    def add_evidence_many(self, items: list[Evidence]) -> None:
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO evidence (
                    id, research_id, sub_question_id, claim, claim_type, source_url,
                    source_title, source_pub_date, extract_text, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.research_id,
                        item.sub_question_id,
                        item.claim,
                        item.claim_type,
                        item.source_url,
                        item.source_title,
                        item.source_pub_date.isoformat(),
                        item.extract_text,
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
                source_url=row["source_url"],
                source_title=row["source_title"],
                source_pub_date=row["source_pub_date"],
                extract_text=row["extract_text"],
                confidence=row["confidence"],
            )
            for row in rows
        ]

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
