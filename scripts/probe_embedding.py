"""Measure a fixed 200-chunk DashScope embedding probe.

The script intentionally accepts local input only and writes aggregate results
under ``artifacts/``.  It neither downloads a corpus nor reads managed golden
sets.  The caller must obtain the price from the authorised account console
and supply it explicitly, so a documentation value cannot silently become an
accounting fact.
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

from deepresearch_agent.llm_config import DASHSCOPE_EMBEDDING_ENDPOINT, DASHSCOPE_EMBEDDING_MODEL

MAX_BATCH_SIZE = 10
DEFAULT_EMBEDDING_ENDPOINT = DASHSCOPE_EMBEDDING_ENDPOINT


def _load_chunks(path: Path) -> list[str]:
    chunks = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(chunks) != 200:
        raise ValueError(f"expected exactly 200 non-empty chunks, got {len(chunks)}")
    return chunks


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def run_probe(
    *,
    chunks: list[str],
    cny_per_1k_input_tokens: float,
    api_key: str,
    endpoint: str,
) -> dict[str, Any]:
    if cny_per_1k_input_tokens < 0:
        raise ValueError("cny_per_1k_input_tokens must be non-negative")
    latencies: list[float] = []
    input_tokens = 0
    dimensions: set[int] = set()
    with httpx.Client(timeout=60.0) as client:
        for offset in range(0, len(chunks), MAX_BATCH_SIZE):
            batch = chunks[offset : offset + MAX_BATCH_SIZE]
            started = time.perf_counter()
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": DASHSCOPE_EMBEDDING_MODEL, "input": batch, "dimensions": 1024},
            )
            latency_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            payload = response.json()
            vectors = payload.get("data", [])
            if len(vectors) != len(batch):
                raise RuntimeError(f"provider returned {len(vectors)} vectors for {len(batch)} inputs")
            latencies.append(latency_ms)
            dimensions.update(len(item["embedding"]) for item in vectors)
            usage = payload.get("usage", {})
            input_tokens += int(usage.get("prompt_tokens", usage.get("total_tokens", 0)) or 0)
    return {
        "model": DASHSCOPE_EMBEDDING_MODEL,
        "sample_chunks": len(chunks),
        "batch_size": MAX_BATCH_SIZE,
        "dimensions_requested": 1024,
        "dimensions_returned": sorted(dimensions),
        "input_tokens_reported": input_tokens,
        "latency_p50_ms": round(statistics.median(latencies), 3),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
        "cny_per_1k_chunks": round(input_tokens * cny_per_1k_input_tokens / 200, 8),
        "price_source": "authorised_account_console_supplied_by_operator",
        "parameters_to_confirm_in_account_console": [
            "supported_dimensions",
            "max_input_tokens_per_item",
            "max_items_per_request",
            "rate_limit_threshold",
        ],
        "measured_at": datetime.now(UTC).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", required=True, type=Path, help="200 local UTF-8 chunks, one per line")
    parser.add_argument("--cny-per-1k-input-tokens", required=True, type=float)
    parser.add_argument("--output", type=Path, default=Path("artifacts/probes/embedding.json"))
    args = parser.parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is required")
    endpoint = os.getenv("DASHSCOPE_EMBEDDING_ENDPOINT", DEFAULT_EMBEDDING_ENDPOINT).strip()
    result = run_probe(
        chunks=_load_chunks(args.chunks),
        cny_per_1k_input_tokens=args.cny_per_1k_input_tokens,
        api_key=api_key,
        endpoint=endpoint,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
