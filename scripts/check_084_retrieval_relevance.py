"""Measure (without gating) RAG evidence whose source filename is off target year."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--target-year", type=int, required=True)
    args = parser.parse_args()
    rows = json.loads((args.package / "audit_bundle/evidence.json").read_text(encoding="utf-8"))
    rag = [row for row in rows if isinstance(row, dict) and "#chunk=" in str(row.get("source_url", ""))]
    target = sum(str(args.target_year) in str(row.get("source_url", "")) for row in rag)
    off_year = len(rag) - target
    ratio = off_year / len(rag) if rag else 0.0
    print(f"rag_evidence={len(rag)}")
    print(f"target_year_evidence={target}")
    print(f"off_year_evidence={off_year}")
    print(f"off_year_ratio={ratio:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
