"""Check that RAG period ends are not misrepresented as publication dates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads((args.package / "audit_bundle/evidence.json").read_text(encoding="utf-8"))
    rag = [row for row in rows if isinstance(row, dict) and (row.get("retrieval_ref") or "#chunk=" in str(row.get("source_url", "")))]
    with_period = sum(bool(row.get("report_period_end")) for row in rag)
    unknown_reason = sum(
        row.get("source_pub_date") in (None, "", "unknown")
        and row.get("source_date_unknown_reason") == "corpus_lacks_publication_date"
        for row in rag
    )
    fabricated = sum(
        bool(row.get("source_pub_date"))
        and row.get("source_pub_date") == row.get("report_period_end")
        for row in rag
    )
    print(f"rag_evidence={len(rag)}")
    print(f"rag_with_period_end={with_period}")
    print(f"rag_pub_date_unknown_with_reason={unknown_reason}")
    print(f"rag_pub_date_fabricated={fabricated}")
    return int(not (with_period == len(rag) and unknown_reason == len(rag) and fabricated == 0))


if __name__ == "__main__":
    raise SystemExit(main())
