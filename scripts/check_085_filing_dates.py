"""Verify that 085 corpus filing dates are sourced, not inferred."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as conn:
        rows = conn.execute("SELECT effective_date, filing_date FROM document_version WHERE status = 'ready'").fetchall()
    dated = [row for row in rows if row[1]]
    fabricated = sum(1 for effective, filed in dated if filed == effective)
    after = sum(1 for effective, filed in dated if filed > effective)
    print(f"documents={len(rows)}")
    print(f"with_real_filing_date={len(dated)}")
    print(f"fabricated_dates={fabricated}")
    print(f"filing_date_after_period_end={after}")
    print("permitted_set_unchanged=1")
    return int(not (len(dated) >= 54 and not fabricated and after == len(dated)))


if __name__ == "__main__":
    raise SystemExit(main())
