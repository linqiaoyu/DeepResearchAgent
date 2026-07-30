"""Registered N=50 real-provider latency sample, accounted in the shared ledger."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path

from dotenv import dotenv_values

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.rag.retrieval import (
    DashScopeEmbeddingProvider,
    DashScopeRerankerProvider,
    ProviderPricing,
    RetrievalCandidate,
)


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "047-provider-latency-n50"
PRICE = ProviderPricing(0.5, "aliyun_model_studio_public_20260729")


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * q)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/runtime/047-assets.db")
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--budget-cny", type=float, default=12.0)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/047/provider_latency_n50.json")
    args = parser.parse_args()
    if args.samples != 50:
        raise SystemExit("registered sample size is exactly 50")
    env = dotenv_values(ROOT / ".env")
    key = str(env.get("DASHSCOPE_API_KEY") or "").strip()
    if not key:
        raise SystemExit("DASHSCOPE_API_KEY is required")
    connection = sqlite3.connect(args.database)
    rows = connection.execute("select id, content from chunk where status='ready' order by id limit 50").fetchall()
    if len(rows) != 50:
        raise SystemExit("local authority storage does not contain 50 ready chunks")
    candidates = [RetrievalCandidate(chunk_id=str(chunk_id), text=str(content)[:512]) for chunk_id, content in rows]
    ledger = LLMClient(ledger_path=ROOT / "artifacts/047/provider_latency_n50_ledger.jsonl", global_ledger_path=ROOT / "data/runtime/llm_ledger.jsonl", budget_cny=args.budget_cny, completion_func=lambda **_: {})
    ledger.start_run(RUN_ID)
    embedding = DashScopeEmbeddingProvider(api_key=key, ledger=ledger, run_id=RUN_ID, pricing=PRICE, dimensions=1024, max_batch_size=1)
    reranker = DashScopeRerankerProvider(api_key=key, ledger=ledger, run_id=RUN_ID, pricing=PRICE)
    for index in range(args.samples):
        query = f"annual report financial disclosure sample {index + 1}"
        embedding.embed([query])
        reranker.rerank(query, candidates, top_n=8)
    entries = [json.loads(line) for line in (ROOT / "artifacts/047/provider_latency_n50_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    embedding_seconds = [float(entry["latency_seconds"]) for entry in entries if entry.get("call_kind") == "embedding"]
    rerank_seconds = [float(entry["latency_seconds"]) for entry in entries if entry.get("call_kind") == "rerank"]
    payload = {"run_id": RUN_ID, "samples": args.samples, "budget_cny": args.budget_cny, "cost_cny": ledger.run_total_cny(RUN_ID), "embedding": {"calls": len(embedding_seconds), "p50_ms": round(statistics.median(embedding_seconds) * 1000, 3), "p95_ms": round(_percentile(embedding_seconds, 0.95) * 1000, 3)}, "rerank": {"calls": len(rerank_seconds), "p50_ms": round(statistics.median(rerank_seconds) * 1000, 3), "p95_ms": round(_percentile(rerank_seconds, 0.95) * 1000, 3)}}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
