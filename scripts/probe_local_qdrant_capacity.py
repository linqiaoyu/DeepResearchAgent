"""Populate disposable local Qdrant collections for zero-cost capacity probes."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

import httpx


def _vector(point_id: int, dimensions: int) -> list[float]:
    """Deterministic non-constant fixture embedding; never calls a provider."""
    return [((point_id * 1103515245 + index * 12345) % 2001 - 1000) / 1000 for index in range(dimensions)]


def _create(client: httpx.Client, name: str, dimensions: int, quantized: bool) -> None:
    client.delete(f"/collections/{name}")
    payload: dict[str, object] = {"vectors": {"size": dimensions, "distance": "Cosine", "on_disk": True}}
    if quantized:
        payload["quantization_config"] = {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": False}}
    response = client.put(f"/collections/{name}", json=payload)
    response.raise_for_status()


def _populate(client: httpx.Client, name: str, points: int, dimensions: int, batch_size: int) -> float:
    started = perf_counter()
    for start in range(0, points, batch_size):
        end = min(points, start + batch_size)
        payload = {"points": [{"id": point_id, "vector": _vector(point_id, dimensions), "payload": {"fixture": True}} for point_id in range(start, end)]}
        response = client.put(f"/collections/{name}/points", params={"wait": "true"}, json=payload)
        response.raise_for_status()
    return perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--points", type=int, default=20_000)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.points < 1 or args.batch_size < 1:
        raise SystemExit("points and batch-size must be positive")
    rows: list[dict[str, object]] = []
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=120.0) as client:
        for name, dimensions, quantized in (("dr047_capacity_1024", 1024, False), ("dr047_quantized_256", 256, True)):
            _create(client, name, dimensions, quantized)
            elapsed = _populate(client, name, args.points, dimensions, args.batch_size)
            info = client.get(f"/collections/{name}").json()["result"]
            rows.append({"collection": name, "dimensions": dimensions, "quantized_int8": quantized, "points": info["points_count"], "indexed_vectors": info["indexed_vectors_count"], "ingest_seconds": round(elapsed, 3)})
    print(json.dumps({"fixture_embedding": True, "rows": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
