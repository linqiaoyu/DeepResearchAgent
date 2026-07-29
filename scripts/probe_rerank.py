"""Measure three fixed local smoke queries against DashScope reranking.

Input is an operator-supplied JSON file containing exactly three query objects;
each object carries a query and exactly 50 local candidate documents.  No query
or document text is persisted in the probe result.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from deepresearch_agent.llm_config import DASHSCOPE_RERANK_MODEL

DEFAULT_RERANK_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 3:
        raise ValueError("expected exactly three probe cases")
    for case in payload:
        if not isinstance(case, dict) or not isinstance(case.get("query"), str):
            raise ValueError("each case needs a string query")
        documents = case.get("documents")
        if not isinstance(documents, list) or len(documents) != 50 or not all(isinstance(value, str) for value in documents):
            raise ValueError("each case needs exactly 50 string documents")
    return payload


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def run_probe(
    *,
    cases: list[dict[str, Any]],
    cny_per_1k_input_tokens: float,
    api_key: str,
    endpoint: str,
) -> dict[str, Any]:
    if cny_per_1k_input_tokens < 0:
        raise ValueError("cny_per_1k_input_tokens must be non-negative")
    latencies: list[float] = []
    input_tokens = 0
    with httpx.Client(timeout=60.0) as client:
        for case in cases:
            started = time.perf_counter()
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": DASHSCOPE_RERANK_MODEL,
                    "query": case["query"],
                    "documents": case["documents"],
                    "top_n": len(case["documents"]),
                },
            )
            latency_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", payload.get("output", {}).get("results", []))
            if not isinstance(results, list) or len(results) != len(case["documents"]):
                raise RuntimeError("provider did not return one score per input document")
            latencies.append(latency_ms)
            usage = payload.get("usage", {})
            input_tokens += int(usage.get("input_tokens", usage.get("total_tokens", 0)) or 0)
    return {
        "model": DASHSCOPE_RERANK_MODEL,
        "sample_queries": len(cases),
        "candidates_per_query": len(cases[0]["documents"]),
        "input_tokens_reported": input_tokens,
        "latency_p50_ms": round(statistics.median(latencies), 3),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
        "cny_per_1k_queries": round(input_tokens * cny_per_1k_input_tokens / len(cases), 8),
        "price_source": "authorised_account_console_supplied_by_operator",
        "parameters_to_confirm_in_account_console": [
            "max_candidates_per_request",
            "max_tokens_per_document",
            "rate_limit_threshold",
        ],
        "measured_at": datetime.now(UTC).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--cny-per-1k-input-tokens", required=True, type=float)
    parser.add_argument("--output", type=Path, default=Path("artifacts/probes/rerank.json"))
    args = parser.parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is required")
    endpoint = os.getenv("DASHSCOPE_RERANK_ENDPOINT", DEFAULT_RERANK_ENDPOINT).strip()
    result = run_probe(
        cases=_load_cases(args.cases),
        cny_per_1k_input_tokens=args.cny_per_1k_input_tokens,
        api_key=api_key,
        endpoint=endpoint,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
