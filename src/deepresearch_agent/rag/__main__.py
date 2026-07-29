from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument(
        "--json-output", type=Path, default=Path("artifacts/rag_benchmark.json")
    )
    benchmark.add_argument(
        "--markdown-output", type=Path, default=Path("artifacts/rag_benchmark.md")
    )
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
    if args.command == "benchmark":
        report = build_benchmark_report(store.rag_status())
        _write_benchmark_report(report, args.json_output, args.markdown_output)
        print(json.dumps(report, ensure_ascii=False))
        return
    raise AssertionError(f"unhandled RAG command: {args.command}")


def build_benchmark_report(status: dict[str, int]) -> dict[str, Any]:
    """Return the stable benchmark schema without inventing unavailable metrics."""

    active_chunks = status["active_chunks"]
    unavailable_reasons = [
        "no_active_chunks" if active_chunks == 0 else "no_retrieval_index",
        "no_frozen_retrieval_labels",
        "no_stage_a_or_b_latency_sample",
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_chunks": active_chunks,
        "index_version": None,
        "metrics": {
            "recall_at_20": None,
            "ndcg_at_10": None,
            "bm25_ndcg_at_10": None,
            "ndcg_at_10_lift": None,
            "stage_a": {"p50_ms": None, "p95_ms": None, "error_rate": None},
            "stage_b": {"p50_ms": None, "p95_ms": None, "cost_cny": None},
            "stage_c": {"p50_ms": None, "p95_ms": None, "inference": None},
            "rebuild_seconds": None,
            "cost_cny": None,
        },
        "unavailable_reasons": unavailable_reasons,
    }


def _write_benchmark_report(report: dict[str, Any], json_output: Path, markdown_output: Path) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = report["metrics"]
    markdown_output.write_text(
        "\n".join(
            (
                "# RAG benchmark",
                "",
                f"- active_chunks: {report['active_chunks']}",
                f"- index_version: {report['index_version']}",
                f"- Recall@20: {metrics['recall_at_20']}",
                f"- nDCG@10: {metrics['ndcg_at_10']}",
                f"- BM25 nDCG@10: {metrics['bm25_ndcg_at_10']}",
                f"- nDCG@10 lift: {metrics['ndcg_at_10_lift']}",
                f"- Stage A p50/p95/error_rate: {metrics['stage_a']}",
                f"- Stage B p50/p95/cost_cny: {metrics['stage_b']}",
                f"- Stage C p50/p95: {metrics['stage_c']}",
                f"- rebuild_seconds: {metrics['rebuild_seconds']}",
                f"- total cost_cny: {metrics['cost_cny']}",
                "",
                "## Unavailable evidence",
                "",
                *[f"- {reason}" for reason in report["unavailable_reasons"]],
                "",
            )
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
