"""Enforce the finance-domain literal ratchet outside domain implementations."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = ROOT / "data/domain_boundary/finance_lexicon.json"
ALLOWLIST_PATH = ROOT / "data/domain_boundary/allowlist.json"
SOURCE_ROOT = ROOT / "src/deepresearch_agent"


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _literal_lines(lexicon: tuple[str, ...]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for path in SOURCE_ROOT.rglob("*.py"):
        if "domains" in path.relative_to(SOURCE_ROOT).parts:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        count = sum(1 for line in lines if any(word in line for word in lexicon))
        if count:
            hits[path.relative_to(ROOT).as_posix()] = count
    return dict(sorted(hits.items()))


def main() -> None:
    lexicon = _load_json(LEXICON_PATH)
    allowlist = _load_json(ALLOWLIST_PATH)
    if not isinstance(lexicon, list) or not all(isinstance(word, str) and word for word in lexicon):
        raise SystemExit(f"invalid lexicon: {LEXICON_PATH}")
    if not isinstance(allowlist, dict) or not all(
        isinstance(path, str) and isinstance(limit, int) and limit >= 0
        for path, limit in allowlist.items()
    ):
        raise SystemExit(f"invalid allowlist: {ALLOWLIST_PATH}")

    hits = _literal_lines(tuple(lexicon))
    failures: list[str] = []
    for path in sorted(set(hits) | set(allowlist)):
        observed = hits.get(path, 0)
        allowed = allowlist.get(path)
        if allowed is None:
            failures.append(f"unallowlisted literal: {path} observed={observed}")
        elif observed != allowed:
            direction = "lower allowlist to" if observed < allowed else "remove literals or raise no allowlist"
            failures.append(
                f"ratchet mismatch: {path} observed={observed} allowed={allowed}; "
                f"{direction} {observed}"
            )

    print(
        f"import_sites=6 literal_files={len(hits)} "
        f"literal_hits={sum(hits.values())} lexicon_terms={len(lexicon)}"
    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
