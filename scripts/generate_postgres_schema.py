"""Generate the checked-in Postgres schema view from versioned migrations."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
OUTPUT = ROOT / "docs" / "postgres_schema.sql"
HEADER = "-- Generated from migrations/*.sql; do not edit by hand.\n\n"


def rendered_schema() -> str:
    files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise ValueError("no migrations found")
    parts = [HEADER]
    for path in files:
        parts.append(f"-- {path.name}\n")
        parts.append(path.read_text(encoding="utf-8").rstrip())
        parts.append("\n\n")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schema()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("docs/postgres_schema.sql is stale; run generate_postgres_schema.py")
        print("postgres_schema_generated=true")
        return
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"generated={OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
