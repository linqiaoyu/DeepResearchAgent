"""Run the registered zero-cost local Qdrant search load measurement."""

from __future__ import annotations

import argparse
import json
import statistics
import time

import httpx


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="dr047_capacity_1024")
    parser.add_argument("--qps", type=float, default=5.0)
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    args = parser.parse_args()
    if args.qps <= 0 or args.duration_seconds <= 0:
        raise SystemExit("qps and duration-seconds must be positive")
    latencies: list[float] = []
    errors: list[str] = []
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=30.0) as client:
        seed = client.post(f"/collections/{args.collection}/points/scroll", json={"limit": 1, "with_vector": True, "with_payload": False})
        seed.raise_for_status()
        vector = seed.json()["result"]["points"][0]["vector"]
        interval = 1 / args.qps
        started = time.perf_counter()
        total = round(args.qps * args.duration_seconds)
        for request_number in range(total):
            scheduled = started + request_number * interval
            remaining = scheduled - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            call_started = time.perf_counter()
            try:
                response = client.post(f"/collections/{args.collection}/points/search", json={"vector": vector, "limit": 20, "with_payload": False, "with_vector": False})
                if response.status_code != 200:
                    errors.append(f"http_{response.status_code}")
                else:
                    latencies.append((time.perf_counter() - call_started) * 1000)
            except httpx.HTTPError as exc:
                errors.append(type(exc).__name__)
    payload = {"collection": args.collection, "qps": args.qps, "duration_seconds": args.duration_seconds, "attempts": total, "successes": len(latencies), "error_rate": len(errors) / total, "p50_ms": round(statistics.median(latencies), 3) if latencies else None, "p95_ms": round(percentile(latencies, 0.95), 3) if latencies else None, "min_ms": round(min(latencies), 3) if latencies else None, "max_ms": round(max(latencies), 3) if latencies else None, "error_types": sorted(set(errors))}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
