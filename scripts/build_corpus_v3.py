"""Rebuild the finance corpus manifest with real disclosure dates.

`finance_v1.json` declared no `published_at` at all, so every document fell back
to its period end. `finance_v2.json` declared one -- the same value for all 60
documents, tagged `retrieved_at_fallback`, which is the day the files were
downloaded, not the day they were published. Retrieval had no real disclosure
date to filter on in either version.

This builds `finance_v3.json` by asking SEC EDGAR when each filing was actually
disclosed. Corpus manifests are immutable per AGENTS.md section 7, so this
writes a new version rather than editing either existing one, and the previous
manifests stay exactly where they are.

The script refuses to emit a manifest it could not fully date. A partially dated
corpus is the failure mode this whole round exists to remove: it looks complete
and silently degrades a subset.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.domains.finance.disclosure_dates import (  # noqa: E402
    SecFilingDateProvider,
)

SOURCE = ROOT / "data/corpus/finance_v2.json"
DESTINATION = ROOT / "data/corpus/finance_v3.json"


def build(source: Path, destination: Path, *, provider: SecFilingDateProvider) -> int:
    payload = json.loads(source.read_text(encoding="utf-8"))
    documents = payload["documents"]
    resolved, unresolved = provider.resolve([str(entry["url"]) for entry in documents])

    rebuilt = []
    anomalies: list[str] = []
    for entry in documents:
        url = str(entry["url"])
        if url not in resolved:
            continue
        disclosure = resolved[url]
        if disclosure.filing_date < str(entry["effective_date"]):
            anomalies.append(
                f"{entry['path']}: filing_date {disclosure.filing_date} precedes "
                f"effective_date {entry['effective_date']}"
            )
        rebuilt.append(
            {
                **{key: value for key, value in entry.items() if key != "published_at_source"},
                "published_at": disclosure.filing_date,
                "published_at_source": disclosure.source,
            }
        )

    for url, reason in sorted(unresolved.items()):
        print(f"unresolved={url} reason={reason}", file=sys.stderr)
    for anomaly in anomalies:
        print(f"anomaly={anomaly}", file=sys.stderr)

    print(f"documents={len(documents)}")
    print(f"resolved={len(rebuilt)}")
    print(f"unresolved={len(unresolved)}")
    if unresolved or anomalies:
        print("corpus_v3=FAIL refusing to write a partially dated manifest", file=sys.stderr)
        return 1

    destination.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "disclosure_dates": {
                    "provider": provider.source_name,
                    "meaning": (
                        "published_at is the date the filing became public in the SEC EDGAR "
                        "submissions index, not the period end and not the retrieval date."
                    ),
                },
                "documents": rebuilt,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lag = [
        (
            _days_between(str(entry["effective_date"]), str(entry["published_at"])),
            entry["path"],
        )
        for entry in rebuilt
    ]
    lag.sort()
    print(f"written={destination.relative_to(ROOT)}")
    print(f"disclosure_lag_days_min={lag[0][0]} max={lag[-1][0]}")
    print(f"median_disclosure_lag_days={lag[len(lag) // 2][0]}")
    return 0


def _days_between(start: str, end: str) -> int:
    from datetime import date

    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    args = parser.parse_args()
    return build(args.source, args.destination, provider=SecFilingDateProvider())


if __name__ == "__main__":
    raise SystemExit(main())
