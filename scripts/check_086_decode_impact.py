"""Measure HTML-entity decoding impact with offline BM25 only."""

from __future__ import annotations

import argparse
import html
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from deepresearch_agent.rag.backends import StorageLexicalBackend
from deepresearch_agent.rag.search import RetrievalFilter
from deepresearch_agent.storage.sqlite_store import SQLiteStore


QUERIES = (
    # Round 085 task card records these four NIO retrieval queries verbatim.
    "NIO Inc. 年度报告",
    "蔚来 2024 第四季度及全年财报 营收",
    "NIO 2024 annual results revenue",
    "蔚来 2024 年报 营业收入 同比",
    # Round 084/085 live topics and checkpointed planner variants.
    "蔚来 2024 年年报的营收与毛利情况",
    "NIO 2024 annual results total revenue",
    "NIO Inc. 2024 annual report gross profit",
    "NIO Inc. 2024 revenue gross margin",
    "PDD 2024 annual report revenue and gross margin",
    "PDD Holdings 2024 annual report total revenue",
    "Pinduoduo FY2024 full year revenue growth",
    "PDD 2024 gross profit gross margin",
    "PDD Holdings Inc. 2024 annual report",
    "NIO 2024 Form 20-F revenue",
    "NIO 2024 gross profit CNY",
    "NIO 2024 total revenues CNY",
    "PDD 2024 Form 20-F revenues",
    "PDD Holdings 2024 gross profit RMB",
    "PDD 2024 online marketing services revenue",
    "PDD 2024 transaction services revenue",
    "蔚来 2024 年度报告 毛利",
    "蔚来 2024 营业收入 毛利",
    "拼多多 2024 年报 营业收入",
    "拼多多 2024 毛利 毛利率",
)


def _decoded_copy(source: Path, destination: Path) -> int:
    if destination.exists():
        destination.unlink()
    shutil.copy2(source, destination)
    changed = 0
    with sqlite3.connect(destination) as connection:
        rows = connection.execute("SELECT id, content FROM chunk").fetchall()
        updates: list[tuple[str, str]] = []
        for chunk_id, content in rows:
            decoded = html.unescape(str(content))
            if decoded != content:
                changed += 1
                updates.append((decoded, str(chunk_id)))
        connection.executemany(
            "UPDATE chunk SET content = ? WHERE id = ?",
            updates,
        )
        connection.commit()
    return changed


def _top_ids(backend: StorageLexicalBackend, query: str) -> list[str]:
    results = backend.search(
        query=query,
        filters=RetrievalFilter(as_of=date(2026, 7, 1)),
        limit=10,
    )
    return [item.chunk_id for item in results]


def _rbo(left: list[str], right: list[str], *, persistence: float = 0.9) -> float:
    overlap = 0
    weighted = 0.0
    left_seen: set[str] = set()
    right_seen: set[str] = set()
    depth_max = max(len(left), len(right), 1)
    for depth in range(1, depth_max + 1):
        if depth <= len(left):
            left_seen.add(left[depth - 1])
        if depth <= len(right):
            right_seen.add(right[depth - 1])
        overlap = len(left_seen & right_seen)
        agreement = overlap / depth
        weighted += (1 - persistence) * agreement * persistence ** (depth - 1)
    return weighted + (overlap / depth_max) * persistence**depth_max


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/runtime/047-assets.db"))
    parser.add_argument(
        "--decoded",
        type=Path,
        default=Path("data/runtime/086-decoded-probe.db"),
    )
    args = parser.parse_args()
    changed_chunks = _decoded_copy(args.source, args.decoded)
    original = StorageLexicalBackend(store=SQLiteStore(args.source))
    decoded = StorageLexicalBackend(store=SQLiteStore(args.decoded))
    overlaps: list[float] = []
    rbos: list[float] = []
    changed_queries = 0
    top1_changes = 0
    for query in QUERIES:
        original_ids = _top_ids(original, query)
        decoded_ids = _top_ids(decoded, query)
        overlap = len(set(original_ids) & set(decoded_ids)) / 10
        overlaps.append(overlap)
        rbos.append(_rbo(original_ids, decoded_ids))
        changed_queries += int(original_ids != decoded_ids)
        top1_changes += int(original_ids[:1] != decoded_ids[:1])
    mean_overlap = sum(overlaps) / len(overlaps)
    mean_rbo = sum(rbos) / len(rbos)
    verdict = (
        "rebuild_not_justified"
        if mean_overlap >= 0.90 and changed_queries / len(QUERIES) <= 0.20
        else "rebuild_justified"
    )
    print(f"queries={len(QUERIES)}")
    print(f"changed_queries={changed_queries}")
    print(f"mean_overlap_at_10={mean_overlap:.6f}")
    print(f"mean_rank_biased_overlap={mean_rbo:.6f}")
    print(f"top1_changes={top1_changes}")
    print(f"decoded_chunks={changed_chunks}")
    print(f"verdict={verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
