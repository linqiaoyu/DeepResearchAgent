"""Fail closed when a B8 run manifest lacks actual provider evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROVIDERS = ("llm", "search", "disclosure", "structured_data")
ACTIVE_T8_PROVIDERS = ("llm", "search", "rag_search")
OPTIONAL_T8_PROVIDERS = ("disclosure", "structured_data")
STAT_FIELDS = (
    "requests",
    "executed_requests",
    "records",
    "symbol_resolution_failures",
    "execution_failures",
)


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("manifest root must be an object")
    return payload


def validate_manifest(
    payload: dict[str, Any], *, require_all_real: bool, require_active_real: bool = False
) -> list[str]:
    failures: list[str] = []
    usage = payload.get("provider_usage")
    stats = payload.get("structured_data_stats")
    fidelity = payload.get("actual_provider_fidelity")
    realness = payload.get("actual_realness")
    if not isinstance(usage, dict):
        return ["missing or invalid provider_usage"]
    if not isinstance(stats, dict):
        return ["missing or invalid structured_data_stats"]
    if not isinstance(fidelity, dict):
        return ["missing or invalid actual_provider_fidelity"]
    if not isinstance(realness, str):
        return ["missing or invalid actual_realness"]
    records = 0
    for sub_question_id, item in stats.items():
        if not isinstance(item, dict):
            failures.append(f"invalid stats for {sub_question_id}")
            continue
        missing = [field for field in STAT_FIELDS if not isinstance(item.get(field), int)]
        if missing:
            failures.append(f"missing or invalid stats for {sub_question_id}: {','.join(missing)}")
            continue
        records += item["records"]
    if not require_active_real:
        if not isinstance(usage.get("structured_data"), int) or usage["structured_data"] < 1:
            failures.append(f"provider_usage.structured_data={usage.get('structured_data')!r}")
        if records < 1:
            failures.append(f"structured_data_stats.records={records}")
    if require_all_real:
        for provider in PROVIDERS:
            if not isinstance(usage.get(provider), int) or usage[provider] < 1:
                failures.append(f"provider_usage.{provider}={usage.get(provider)!r}")
            if fidelity.get(provider) != "real":
                failures.append(f"actual_provider_fidelity.{provider}={fidelity.get(provider)!r}")
        if realness != "real":
            failures.append(f"actual_realness={realness!r}")
    if require_active_real:
        optional_unused = False
        for provider in ACTIVE_T8_PROVIDERS:
            if not isinstance(usage.get(provider), int) or usage[provider] < 1:
                failures.append(f"provider_usage.{provider}={usage.get(provider)!r}")
            if fidelity.get(provider) != "real":
                failures.append(f"actual_provider_fidelity.{provider}={fidelity.get(provider)!r}")
        for provider in OPTIONAL_T8_PROVIDERS:
            provider_usage = usage.get(provider)
            provider_fidelity = fidelity.get(provider)
            if not isinstance(provider_usage, int) or provider_usage < 0:
                failures.append(f"provider_usage.{provider}={provider_usage!r}")
            elif provider_usage == 0:
                optional_unused = True
                if provider_fidelity != "unused":
                    failures.append(f"actual_provider_fidelity.{provider}={provider_fidelity!r}")
            elif provider_fidelity != "real":
                failures.append(f"actual_provider_fidelity.{provider}={provider_fidelity!r}")
        expected_realness = "mixed" if optional_unused else "real"
        if realness != expected_realness:
            failures.append(f"actual_realness={realness!r}; expected {expected_realness!r}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--require-structured", action="store_true")
    mode.add_argument("--require-all-real", action="store_true")
    mode.add_argument("--require-active-real", action="store_true")
    args = parser.parse_args()
    try:
        failures = validate_manifest(
            _load_manifest(args.manifest),
            require_all_real=args.require_all_real,
            require_active_real=args.require_active_real,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures = [str(exc)]
    if failures:
        print("manifest validation failed: " + "; ".join(failures))
        raise SystemExit(1)
    print("manifest validation passed")


if __name__ == "__main__":
    main()
