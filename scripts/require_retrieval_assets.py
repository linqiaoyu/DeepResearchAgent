"""Fail closed when a retrieval asset database is missing or not a SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def require_retrieval_assets(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"retrieval assets database missing: {path}")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as error:
        raise ValueError(f"retrieval assets database unreadable: {path}") from error
    if "chunk" not in names:
        raise ValueError(f"retrieval assets database lacks chunk table: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    require_retrieval_assets(args.database)
    print(f"retrieval_assets_ok={args.database.name}")


if __name__ == "__main__":
    main()
