from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.rag.ingest import ingest_and_persist
from deepresearch_agent.settings import load_settings
from deepresearch_agent.storage import build_store


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m deepresearch_agent.rag")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--input", type=Path, required=True)
    ingest.add_argument("--corpus", type=Path, required=True)
    commands.add_parser("status")
    rebuild = commands.add_parser("rebuild")
    rebuild.add_argument("--input", type=Path, required=True)
    rebuild.add_argument("--corpus", type=Path, required=True)
    commands.add_parser("benchmark")
    args = parser.parse_args()
    settings = load_settings()
    store = build_store(settings)
    if args.command in {"ingest", "rebuild"}:
        report = ingest_and_persist(
            input_dir=args.input,
            corpus_path=args.corpus,
            store=store,
            max_pdf_pages=settings.rag_ingest_max_pages,
        )
        print(json.dumps(report.__dict__, ensure_ascii=False))
        return
    if args.command == "status":
        print(json.dumps(store.rag_status(), ensure_ascii=False))
        return
    raise SystemExit(f"{args.command} is not available until the index backend is configured")


if __name__ == "__main__":
    main()
