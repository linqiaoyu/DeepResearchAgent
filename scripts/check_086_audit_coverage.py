"""Validate the round-086 named-stage silent-degradation audit."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


STAGES = tuple(f"S{index:02d}" for index in range(1, 15))
SEVERITIES = {"高", "中", "低"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    lines = args.audit.read_text(encoding="utf-8").splitlines()
    rows: list[list[str]] = []
    rows_missing_columns = 0
    for line in lines:
        if not re.match(r"^\|\s*S\d{2}\b", line):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if len(columns) != 5 or any(not column for column in columns):
            rows_missing_columns += 1
            continue
        rows.append(columns)
    covered = {columns[0].split()[0] for columns in rows}
    high = [columns for columns in rows if columns[4] == "高"]
    high_unaddressed = [
        columns
        for columns in high
        if columns[3] == "无"
        or "INCOMPLETE" in columns[3]
        or "未处理" in columns[3]
    ]
    invalid_severity = sum(columns[4] not in SEVERITIES for columns in rows)
    print(f"stages_covered={len(covered & set(STAGES))}")
    print(f"rows={len(rows)}")
    print(f"rows_missing_columns={rows_missing_columns}")
    print(f"high_severity={len(high)}")
    print(f"high_severity_unaddressed={len(high_unaddressed)}")
    valid = (
        covered == set(STAGES)
        and len(rows) >= 20
        and rows_missing_columns == 0
        and invalid_severity == 0
        and bool(high)
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
