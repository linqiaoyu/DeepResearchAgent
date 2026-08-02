"""Check that reader-visible footnotes are unique by source URL."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    report = (args.package / "report.md").read_text(encoding="utf-8")
    entries = re.findall(r"^\[\^(\d+)\]:\s+.*?\s(https?://\S+)", report, re.M)
    urls = [url for _, url in entries]
    duplicates = len(urls) - len(set(urls))
    uuid_titles = sum(bool(re.search(r"retrieval chunk [0-9a-f-]{36}", line, re.I)) for line in report.splitlines() if line.startswith("[^"))
    print(f"footnote_count={len(entries)}")
    print(f"distinct_source_urls={len(set(urls))}")
    print(f"duplicate_footnotes={duplicates}")
    print(f"uuid_titles={uuid_titles}")
    return int(bool(duplicates or uuid_titles))


if __name__ == "__main__":
    raise SystemExit(main())
