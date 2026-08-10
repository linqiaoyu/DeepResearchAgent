"""Refuse a schema that drifted between the two storage backends.

R112 found that `document_version.filing_date` existed only in SQLite. It was
added to `SQLiteStore._setup()` in R085 and never written as a migration, so the
Postgres table simply did not have the column. Nothing failed: the Postgres read
path avoided the error by not selecting it, and returned an empty disclosure
date instead. Twelve columns had been added that way and eleven had made it into
`migrations/`; the twelfth silently defeated the point-in-time guard it existed
to feed.

The two backends evolve through mechanisms that cannot see each other --
`_ensure_column()` on one side, versioned SQL on the other -- so parity is not
something either mechanism can enforce. This reconciles them directly: build the
SQLite schema in a temporary database, parse the Postgres schema out of the
migrations, and compare. Every difference must be declared in
``data/storage_schema_parity.json`` with a reason, and anything undeclared
fails.

`--self-test` proves the check can fail: it injects a column into the parsed
Postgres schema and asserts the comparison rejects it.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.storage.sqlite_store import SQLiteStore  # noqa: E402

MIGRATIONS_DIR = ROOT / "migrations"
PARITY_PATH = ROOT / "data/storage_schema_parity.json"

#: Table-level constraint keywords that are not column definitions.
_CONSTRAINT_KEYWORDS = ("CHECK", "UNIQUE", "PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT")

_CREATE_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", re.S)
_ADD_COLUMN = re.compile(r"ALTER TABLE (\w+) ADD COLUMN(?: IF NOT EXISTS)? (\w+)")


def sqlite_schema() -> dict[str, set[str]]:
    """Build a fresh SQLite database and read back what the store created."""

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "parity.db"
        SQLiteStore(path)
        connection = sqlite3.connect(path)
        try:
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            return {
                table: {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
                for table in tables
            }
        finally:
            connection.close()


def postgres_schema() -> dict[str, set[str]]:
    """Derive the Postgres schema from the versioned migrations alone."""

    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    )
    schema: dict[str, set[str]] = {}
    for match in _CREATE_TABLE.finditer(sql):
        columns: set[str] = set()
        for line in match.group(2).splitlines():
            stripped = line.strip().rstrip(",")
            if not stripped or stripped.upper().startswith(_CONSTRAINT_KEYWORDS):
                continue
            columns.add(stripped.split()[0])
        schema[match.group(1)] = columns
    for match in _ADD_COLUMN.finditer(sql):
        schema.setdefault(match.group(1), set()).add(match.group(2))
    return schema


def compare(sqlite: dict[str, set[str]], postgres: dict[str, set[str]]) -> list[str]:
    """Return every difference the declared parity file does not account for."""

    declared = json.loads(PARITY_PATH.read_text(encoding="utf-8"))
    table_map: dict[str, str] = declared["table_map"]
    postgres_only_tables: dict[str, str] = declared["postgres_only_tables"]
    sqlite_only_tables: dict[str, str] = declared["sqlite_only_tables"]
    column_exceptions: dict[str, dict[str, object]] = declared["column_exceptions"]

    failures: list[str] = []
    seen_postgres: set[str] = set()
    for sqlite_table, sqlite_columns in sorted(sqlite.items()):
        postgres_table = table_map.get(sqlite_table, sqlite_table)
        if postgres_table not in postgres:
            if sqlite_table not in sqlite_only_tables:
                failures.append(
                    f"table {sqlite_table!r} exists in SQLite but has no migration "
                    f"(expected Postgres table {postgres_table!r})"
                )
            continue
        seen_postgres.add(postgres_table)
        exception = column_exceptions.get(sqlite_table, {})
        allowed_postgres_only = set(exception.get("postgres_only", []) or [])
        allowed_sqlite_only = set(exception.get("sqlite_only", []) or [])
        postgres_columns = postgres[postgres_table]
        sqlite_only = sqlite_columns - postgres_columns - allowed_sqlite_only
        postgres_only = postgres_columns - sqlite_columns - allowed_postgres_only
        if sqlite_only:
            failures.append(
                f"{sqlite_table}: column(s) {sorted(sqlite_only)} exist in SQLite but "
                f"not in migrations/ -- add a migration or declare the difference"
            )
        if postgres_only:
            failures.append(
                f"{sqlite_table}: column(s) {sorted(postgres_only)} exist in migrations/ "
                f"but not in SQLite -- add the column or declare the difference"
            )
    for postgres_table in sorted(set(postgres) - seen_postgres):
        if postgres_table not in postgres_only_tables:
            failures.append(
                f"table {postgres_table!r} exists in migrations/ with no SQLite "
                f"counterpart and no declared reason"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    sqlite = sqlite_schema()
    postgres = postgres_schema()

    if args.self_test:
        # Mutating either side must be caught. Injecting an undeclared column
        # into the Postgres schema is the exact shape of the drift that went
        # unnoticed for 27 rounds, with the direction reversed.
        mutated = {table: set(columns) for table, columns in postgres.items()}
        mutated["document_version"].add("drifted_column")
        if not compare(sqlite, mutated):
            print(
                "storage_schema_parity=FAIL self-test did not detect an injected column",
                file=sys.stderr,
            )
            return 1

    failures = compare(sqlite, postgres)
    if failures:
        for failure in failures:
            print(f"storage_schema_parity=FAIL {failure}", file=sys.stderr)
        return 1
    shared = len(set(sqlite) & {*postgres, *sqlite})
    columns = sum(len(values) for values in sqlite.values())
    print(f"storage_schema_parity=PASS tables={shared} sqlite_columns={columns} undeclared_diffs=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
