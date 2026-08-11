"""Prove that production provider boundaries are registered and controlled."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src/deepresearch_agent"
REGISTRY_PATH = ROOT / "data/external_call_registry.json"
REQUIRED_CONTROLS = ("timeout", "retry", "request_budget", "degradation")
VALID_CATEGORIES = {"llm", "tool", "rag", "mcp"}
LLM_GATEWAY = "src/deepresearch_agent/llm/client.py"


def discover_external_boundaries(source_root: Path = SOURCE_ROOT) -> set[str]:
    """Find files that own an SDK, HTTP, or subprocess provider primitive."""

    discovered: set[str] = set()
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        indicators = (
            "import httpx" in text,
            'import_module("litellm")' in text,
            "subprocess.Popen(" in text,
            "multiprocessing.get_context(" in text,
        )
        if any(indicators):
            discovered.add(path.relative_to(ROOT).as_posix())
    return discovered


def evaluate(registry: Any, *, discovered: set[str] | None = None) -> list[str]:
    failures: list[str] = []
    if not isinstance(registry, dict):
        return ["external-call registry must be an object"]
    if registry.get("schema_version") != 1:
        failures.append("schema_version must be 1")
    if not str(registry.get("scope", "")).strip():
        failures.append("scope must be non-empty")
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        return [*failures, "entries must be an object"]
    observed = set(entries)
    actual = discover_external_boundaries() if discovered is None else discovered
    if observed != actual:
        failures.append(
            f"registered external boundaries must be exactly {sorted(actual)}, "
            f"got {sorted(observed)}"
        )
    for path, raw_entry in sorted(entries.items()):
        if not isinstance(raw_entry, dict):
            failures.append(f"{path}: entry must be an object")
            continue
        category = raw_entry.get("category")
        if category not in VALID_CATEGORIES:
            failures.append(f"{path}: invalid category {category!r}")
        if not str(raw_entry.get("gateway", "")).strip():
            failures.append(f"{path}: gateway must be non-empty")
        for control in REQUIRED_CONTROLS:
            if not str(raw_entry.get(control, "")).strip():
                failures.append(f"{path}: missing {control} control")
        evidence_files = raw_entry.get("evidence_files")
        evidence_tokens = raw_entry.get("evidence_tokens")
        if not isinstance(evidence_files, list) or not evidence_files:
            failures.append(f"{path}: evidence_files must be a non-empty list")
            continue
        if not isinstance(evidence_tokens, list) or not evidence_tokens:
            failures.append(f"{path}: evidence_tokens must be a non-empty list")
            continue
        evidence = ""
        for evidence_file in evidence_files:
            candidate = ROOT / str(evidence_file)
            if not candidate.is_file():
                failures.append(f"{path}: missing evidence file {evidence_file}")
                continue
            evidence += candidate.read_text(encoding="utf-8")
        for token in evidence_tokens:
            if not isinstance(token, str) or not token or token not in evidence:
                failures.append(f"{path}: control evidence token is absent: {token!r}")
    llm_entry = entries.get(LLM_GATEWAY)
    if not isinstance(llm_entry, dict) or llm_entry.get("gateway") != "LLMClient":
        failures.append("all LLM provider calls must be owned by LLMClient")
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative == LLM_GATEWAY:
            continue
        if "litellm.completion(" in path.read_text(encoding="utf-8"):
            failures.append(f"LLM provider bypass outside LLMClient: {relative}")
    return failures


def _self_test(registry: dict[str, Any], discovered: set[str]) -> None:
    if evaluate(registry, discovered=discovered):
        raise SystemExit("external_call_closure_self_test=FAIL production registry is dirty")
    entries = registry["entries"]
    sample = "src/deepresearch_agent/rag/qdrant_index.py"
    cases = {
        "missing_registration": {
            **registry,
            "entries": {key: value for key, value in entries.items() if key != sample},
        },
        "missing_timeout": {
            **registry,
            "entries": {
                **entries,
                sample: {**entries[sample], "timeout": ""},
            },
        },
        "wrong_llm_gateway": {
            **registry,
            "entries": {
                **entries,
                LLM_GATEWAY: {**entries[LLM_GATEWAY], "gateway": "DirectSDK"},
            },
        },
        "missing_evidence": {
            **registry,
            "entries": {
                **entries,
                sample: {
                    **entries[sample],
                    "evidence_tokens": [*entries[sample]["evidence_tokens"], "not-present"],
                },
            },
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken, discovered=discovered):
            raise SystemExit(f"external_call_closure_self_test=FAIL accepted {label}")
    bypass = {*discovered, "src/deepresearch_agent/new_provider_bypass.py"}
    if not evaluate(registry, discovered=bypass):
        raise SystemExit("external_call_closure_self_test=FAIL accepted new bypass")
    print(f"external_call_closure_self_test=PASS cases={len(cases) + 2}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    discovered = discover_external_boundaries()
    if args.self_test:
        _self_test(registry, discovered)
    failures = evaluate(registry, discovered=discovered)
    entries = registry.get("entries", {})
    controlled = sum(
        isinstance(entry, dict)
        and all(str(entry.get(name, "")).strip() for name in REQUIRED_CONTROLS)
        for entry in entries.values()
    )
    metrics = {
        "registered": len(entries),
        "discovered": len(discovered),
        "controlled": controlled,
        "coverage": controlled / len(discovered) if discovered else 1.0,
        "llm_bypasses": sum("LLM provider bypass" in item for item in failures),
    }
    if args.json:
        print(json.dumps(metrics, sort_keys=True))
    else:
        print(" ".join(f"{name}={value}" for name, value in metrics.items()))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
