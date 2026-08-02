"""Copy the immutable 047 corpus and attach verified SEC filing dates."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path


_ARCHIVE = re.compile(r"/data/(\d+)/(\d{18})/")


def sec_submissions(cik: str) -> dict[str, object]:
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    result = subprocess.run(
        ["curl", "-fsSL", "-H", "User-Agent: DeepResearchAgent research@example.invalid", url],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    return payload if isinstance(payload, dict) else {}


def filing_dates(urls: list[str]) -> dict[str, str]:
    by_cik: dict[str, set[str]] = {}
    for url in urls:
        match = _ARCHIVE.search(url)
        if match:
            by_cik.setdefault(match.group(1), set()).add(match.group(2))
    dates: dict[tuple[str, str], str] = {}
    for cik, accessions in sorted(by_cik.items()):
        recent = sec_submissions(cik).get("filings", {})
        rows = recent.get("recent", {}) if isinstance(recent, dict) else {}
        accessn = rows.get("accessionNumber", []) if isinstance(rows, dict) else []
        filed = rows.get("filingDate", []) if isinstance(rows, dict) else []
        for accession, date_value in zip(accessn, filed, strict=False):
            normalized = str(accession).replace("-", "")
            if normalized in accessions and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(date_value)):
                dates[(cik, normalized)] = str(date_value)
    return {
        url: dates[(match.group(1), match.group(2))]
        for url in urls
        if (match := _ARCHIVE.search(url)) and (match.group(1), match.group(2)) in dates
    }


def backfill(source: Path, destination: Path) -> tuple[int, int]:
    if not destination.exists():
        shutil.copy2(source, destination)
    with sqlite3.connect(destination) as conn:
        conn.execute("ALTER TABLE document_version ADD COLUMN filing_date TEXT NOT NULL DEFAULT ''") if "filing_date" not in {row[1] for row in conn.execute("PRAGMA table_info(document_version)")} else None
        rows = conn.execute("SELECT document_version.id, document.canonical_url FROM document_version JOIN document ON document.id = document_version.document_id WHERE document_version.status = 'ready'").fetchall()
        dates = filing_dates([str(row[1]) for row in rows])
        conn.executemany("UPDATE document_version SET filing_date = ? WHERE id = ?", [(dates[str(url)], version_id) for version_id, url in rows if str(url) in dates])
        conn.commit()
    return len(rows), len(dates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/runtime/047-assets.db"))
    parser.add_argument("--database", type=Path, default=Path("data/runtime/085-assets.db"))
    args = parser.parse_args()
    documents, dated = backfill(args.source, args.database)
    print(f"documents={documents}")
    print(f"with_real_filing_date={dated}")
    return 0 if dated >= 54 else 1


if __name__ == "__main__":
    raise SystemExit(main())
