from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.agents import ExtractorAgent
from deepresearch_agent.schemas import Source, SubQuestion
from deepresearch_agent.security import ContentIngressGuard


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/injection_corpus.json"
INGRESS_FILES = {
    "web": ROOT / "src/deepresearch_agent/agents/extractor.py",
    "rag": ROOT / "src/deepresearch_agent/agents/extractor.py",
    "mcp": ROOT / "src/deepresearch_agent/mcp/client.py",
    "skill": ROOT / "src/deepresearch_agent/skills/loader.py",
}


def collect_metrics() -> dict[str, int | float]:
    rows: list[dict[str, Any]] = json.loads(
        CORPUS.read_text(encoding="utf-8")
    )
    attacks = [item for item in rows if item.get("risky") is True]
    guard = ContentIngressGuard(enabled=True)
    successes = 0
    decisions = []
    for kind in ("web", "rag", "mcp", "skill"):
        for attack in attacks:
            protected, decision = guard.protect(
                ingress_kind=kind,
                content=str(attack["text"]),
                source=f"registered-attack://{attack['id']}",
            )
            decisions.append(decision)
            if kind == "web":
                successes += int(
                    decision.disposition != "quarantined"
                    or "<UNTRUSTED_EXTERNAL_DATA" not in protected
                )
            else:
                successes += int(
                    decision.disposition != "rejected" or bool(protected)
                )

    safe_text = (
        "The annual report states revenue increased by 12% in 2024, while "
        "operating cash flow remained positive."
    )
    source = Source(
        title="safe annual report",
        url="https://safe.example/report",
        source_type="web",
        published_at=date(2025, 4, 1),
        content=safe_text,
    )
    question = SubQuestion(
        id="safe",
        question="What changed?",
        search_queries=["annual report revenue"],
    )
    enabled = ExtractorAgent(injection_guard_enabled=True).extract(
        "safe-run", question, [source]
    )
    disabled = ExtractorAgent(injection_guard_enabled=False).extract(
        "safe-run", question, [source]
    )
    enabled_reader = [
        (item.claim, item.extract_text, item.source_url) for item in enabled
    ]
    disabled_reader = [
        (item.claim, item.extract_text, item.source_url) for item in disabled
    ]
    source_text = {
        kind: path.read_text(encoding="utf-8")
        for kind, path in INGRESS_FILES.items()
    }
    production_wiring = sum(
        marker in source_text[kind]
        for kind, marker in {
            "web": 'else "web"',
            "rag": '"rag" if source.retrieval_ref',
            "mcp": 'ingress_kind="mcp"',
            "skill": 'ingress_kind="skill"',
        }.items()
    )
    distinct_kinds = {item.ingress_kind for item in decisions}
    return {
        "guarded_ingress_kinds": len(distinct_kinds),
        "registered_attacks": len(attacks) * 4,
        "registered_injection_successes": successes,
        "trust_label_coverage": sum(
            item.trust_label == "untrusted_external" for item in decisions
        )
        / len(decisions),
        "rejection_locator_coverage": sum(
            item.locator.startswith("content-security:")
            for item in decisions
        )
        / len(decisions),
        "normal_reader_visible_match": float(
            enabled_reader == disabled_reader and bool(enabled_reader)
        ),
        "production_ingress_wiring": production_wiring,
    }


def validate(metrics: dict[str, int | float]) -> list[str]:
    expected: dict[str, int | float] = {
        "guarded_ingress_kinds": 4,
        "registered_injection_successes": 0,
        "trust_label_coverage": 1.0,
        "rejection_locator_coverage": 1.0,
        "normal_reader_visible_match": 1.0,
        "production_ingress_wiring": 4,
    }
    failures = [
        f"{key}: expected {target!r}, got {metrics.get(key)!r}"
        for key, target in expected.items()
        if metrics.get(key) != target
    ]
    if metrics.get("registered_attacks", 0) < 160:
        failures.append("registered_attacks must cover the real corpus x4")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = collect_metrics()
    failures = validate(metrics)
    print(json.dumps(metrics, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))
    if args.self_test:
        broken = dict(metrics)
        broken["guarded_ingress_kinds"] = 3
        if not validate(broken):
            raise SystemExit("negative self-test accepted an ingress bypass")
        print("content_security_ingress_self_test=PASS positive=1 negative=1")


if __name__ == "__main__":
    main()
