from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from deepresearch_agent.storage.sqlite_store import SQLiteStore


class EnsureColumnRaceTests(unittest.TestCase):
    """R091: losing the ADD COLUMN race means the column exists, not a failure.

    Two request-scoped engines opening the same database both read the schema,
    both see the column missing, and both issue the ALTER. Before this, the
    loser raised `duplicate column name` out of migration and failed the run;
    R087 recorded exactly that and retried past it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "race.db"
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE chunk (id TEXT PRIMARY KEY)")
        self.store = SQLiteStore.__new__(SQLiteStore)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_a_lost_race_is_absorbed(self) -> None:
        winner = self._conn()
        loser = self._conn()
        try:
            # The loser reads the schema first, then the winner commits the
            # column: exactly the interleaving that used to raise.
            self.assertFalse(SQLiteStore._has_column(loser, "chunk", "published_at"))
            SQLiteStore._ensure_column(
                self.store, winner, "chunk", "published_at", "TEXT NOT NULL DEFAULT ''"
            )
            winner.commit()

            SQLiteStore._ensure_column(
                self.store, loser, "chunk", "published_at", "TEXT NOT NULL DEFAULT ''"
            )

            self.assertTrue(SQLiteStore._has_column(loser, "chunk", "published_at"))
        finally:
            winner.close()
            loser.close()

    def test_a_genuine_migration_error_still_raises(self) -> None:
        """Absorbing the race must not swallow a real schema failure."""

        conn = self._conn()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore._ensure_column(
                    self.store, conn, "no_such_table", "col", "TEXT"
                )
        finally:
            conn.close()

    def test_concurrent_migrations_all_succeed(self) -> None:
        failures: list[BaseException] = []
        lock = threading.Lock()
        barrier = threading.Barrier(8)

        def migrate() -> None:
            conn = self._conn()
            try:
                barrier.wait(timeout=10)
                SQLiteStore._ensure_column(
                    self.store, conn, "chunk", "entity_id", "TEXT NOT NULL DEFAULT ''"
                )
                conn.commit()
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted
                with lock:
                    failures.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=migrate) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(failures, [])
        conn = self._conn()
        try:
            self.assertTrue(SQLiteStore._has_column(conn, "chunk", "entity_id"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
