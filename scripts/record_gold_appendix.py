from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.tools.recording_search import RecordingSearchProvider, normalize_query_key
from deepresearch_agent.tools.tavily_search import TavilySearchProvider


def main() -> None:
    args = _parse_args()
    _load_env(Path(args.env_path))
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TAVILY_API_KEY is required for appendix recording")

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    queries = manifest.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError("appendix manifest queries must be a list")
    if len(queries) > args.max_credits:
        raise ValueError("basic query count exceeds appendix credit cap")

    recording_dir = Path(args.recording_dir)
    ledger_path = Path(args.ledger_path)
    live = TavilySearchProvider(
        api_key,
        search_depth="basic",
        include_raw_content=True,
        ledger_path=ledger_path,
        credit_warning_threshold=max(1, args.max_credits - 20),
        credit_hard_threshold=args.max_credits,
    )
    provider = RecordingSearchProvider(
        "record",
        recording_dir=recording_dir,
        live_provider=live,
        as_of=date.fromisoformat(args.as_of),
    )
    before = _ledger_credits(ledger_path)
    rows: list[dict[str, Any]] = []
    for item in queries:
        query = str(item["query"])
        top_k = int(item.get("top_k", 5))
        source_type = item.get("source_type")
        sources = provider.search(query, top_k=top_k, source_type=source_type)
        key = normalize_query_key(query, top_k=top_k, source_type=source_type)
        filename = hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json"
        rows.append(
            {
                "id": item["id"],
                "question_id": item["question_id"],
                "slots": item["slots"],
                "query": query,
                "reason": item["reason"],
                "recording_file": filename,
                "source_ids": [source.id for source in sources],
                "source_urls": [source.url for source in sources],
                "result_count": len(sources),
                "status": "complete" if sources else "unresolved",
            }
        )
        print(f"{item['id']}: {len(sources)} sources", flush=True)

    used = _ledger_credits(ledger_path) - before
    index = {
        "version": manifest.get("version", "v1.1"),
        "as_of": args.as_of,
        "search_depth": "basic",
        "credit_cap": args.max_credits,
        "credits_used_this_run": used,
        "credits_used_task_total": _ledger_credits(ledger_path),
        "queries": rows,
    }
    index_path = recording_dir / "index_v11.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(index, ensure_ascii=False, indent=2))


def _ledger_credits(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("refused"):
            total += int(row.get("credit_estimate", 0) or 0)
    return total


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record bounded Tavily basic searches for gold appendix evidence.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--recording-dir", default="data/recordings/gold_appendix")
    parser.add_argument("--ledger-path", default="_collab/008a_gold-v11/tavily_ledger.jsonl")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--max-credits", type=int, default=120)
    return parser.parse_args()


if __name__ == "__main__":
    main()
