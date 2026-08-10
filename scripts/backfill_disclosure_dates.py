"""Give existing databases the disclosure dates their rows never had.

R112 taught the pipeline to record a filing's disclosure date. R113 removed the
last place that substituted the reporting-period end when none was declared.
Neither helps a database written before those rounds: its rows carry either an
empty `filing_date`, or a `filing_date` equal to the period end because that is
what the old code stored. The first is honest and invisible; the second is the
lookahead bias, frozen into data.

This migrates such a database. For every ready document version it asks SEC
EDGAR when the filing was actually disclosed, and writes only what the registry
answers. Rows it cannot resolve are reported and left empty -- which under the
R113 retrieval rule means withheld, not back-dated. That is the intended
outcome: an unknown date should cost you recall, not correctness.

Run it against a copy. `--dry-run` reports without writing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.domains.finance.disclosure_dates import (  # noqa: E402
    SecFilingDateProvider,
)


def _rows(connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return [
        (str(row[0]), str(row[1]), str(row[2] or ""), str(row[3]))
        for row in connection.execute(
            "SELECT document_version.id, document.canonical_url, "
            "document_version.filing_date, document_version.effective_date "
            "FROM document_version JOIN document "
            "ON document.id = document_version.document_id "
            "WHERE document_version.status = 'ready'"
        )
    ]


def backfill(database: Path, *, dry_run: bool, provider: SecFilingDateProvider) -> int:
    connection = sqlite3.connect(database)
    try:
        rows = _rows(connection)
        if not rows:
            print("document_versions=0 nothing to migrate")
            return 0

        # A filing_date equal to the period end is what the pre-R113 write path
        # produced when nothing declared a disclosure date. It is indistinguishable
        # from a genuine same-day disclosure, which for an annual report does not
        # happen, so it is treated as unset and re-resolved.
        suspect = [row for row in rows if not row[2] or row[2] == row[3]]
        resolved, unresolved = provider.resolve([row[1] for row in suspect])

        updates = [
            (resolved[url].filing_date, version_id)
            for version_id, url, _filing, _effective in suspect
            if url in resolved
        ]
        print(f"document_versions={len(rows)}")
        print(f"needing_migration={len(suspect)}")
        print(f"resolved={len(updates)}")
        print(f"unresolved={len(unresolved)}")
        for url, reason in sorted(unresolved.items()):
            print(f"unresolved_url={url} reason={reason}", file=sys.stderr)

        if dry_run:
            print("dry_run=true no rows written")
            return 0

        connection.executemany(
            "UPDATE document_version SET filing_date = ? WHERE id = ?", updates
        )
        connection.executemany(
            "UPDATE chunk SET published_at = ? WHERE document_version_id = ?", updates
        )
        # Anything still unresolved must not keep a back-dated value.
        connection.execute(
            "UPDATE document_version SET filing_date = '' WHERE filing_date = effective_date"
        )
        connection.execute(
            "UPDATE chunk SET published_at = '' WHERE document_version_id IN "
            "(SELECT id FROM document_version WHERE filing_date = '')"
        )
        connection.commit()

        remaining = connection.execute(
            "SELECT count(*) FROM document_version WHERE status = 'ready' AND filing_date = ''"
        ).fetchone()[0]
        print(f"written={len(updates)}")
        print(f"still_undated={remaining} (withheld from as-of retrieval, not back-dated)")
        return 0
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database.is_file():
        print(f"no such database: {args.database}", file=sys.stderr)
        return 1
    return backfill(args.database, dry_run=args.dry_run, provider=SecFilingDateProvider())


if __name__ == "__main__":
    raise SystemExit(main())
