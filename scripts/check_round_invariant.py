"""Portable regex/file invariants used by the 043 progress ledger."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".txt"}


def _files(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = ROOT / raw
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix in TEXT_SUFFIXES
            )
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("count", "files"))
    parser.add_argument("--pattern")
    parser.add_argument("--glob")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    paths = _files(args.paths)
    if args.mode == "files":
        if not args.glob:
            parser.error("files mode requires --glob")
        matches = [path for path in paths if path.match(args.glob)]
        for path in matches:
            print(path.relative_to(ROOT))
        raise SystemExit(0 if matches else 1)
    if not args.pattern:
        parser.error("count mode requires --pattern")
    pattern = re.compile(args.pattern, re.MULTILINE)
    count = sum(
        len(pattern.findall(path.read_text(encoding="utf-8")))
        for path in paths
    )
    if count:
        print(count)
        return
    raise SystemExit(1)


if __name__ == "__main__":
    main()
