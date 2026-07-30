"""Derive issuer names from the immutable local SEC filing corpus."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from pathlib import Path


REGISTRANT_RE = re.compile(
    r'name=["\']dei:EntityRegistrantName["\'][^>]*>\s*(?:<[^>]+>\s*)*([^<]+)',
    re.IGNORECASE,
)


def build_catalog(corpus: Path, source_dir: Path) -> dict[str, object]:
    entries = json.loads(corpus.read_text(encoding="utf-8"))["documents"]
    names: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        path = source_dir / entry["path"]
        entity_id = path.stem.split("_", 1)[0]
        match = REGISTRANT_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        if not match:
            raise ValueError(f"missing dei:EntityRegistrantName: {entry['path']}")
        names[entity_id].add(" ".join(html.unescape(match.group(1)).split()))
    return {"source": "SEC filing dei:EntityRegistrantName", "documents": len(entries), "issuers": {key: sorted(value) for key, value in sorted(names.items())}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_catalog(args.corpus, args.input)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"documents": result["documents"], "issuer_count": len(result["issuers"]) }))


if __name__ == "__main__":
    main()
