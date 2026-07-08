from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from deepresearch_agent.schemas import EvaluationResult
from deepresearch_agent.settings import project_root
from deepresearch_agent.workflow import DeepResearchEngine

QUALITY_METRICS = (
    "avg_citation_accuracy",
    "avg_citation_resolution_rate",
    "avg_faithfulness",
    "avg_critic_catch_rate",
)
OPERATIONAL_METRICS = (
    "avg_cost_usd",
    "avg_latency_seconds",
    "avg_token_used",
)


class EvaluationHarness:
    def __init__(self, engine: DeepResearchEngine | None = None, eval_path: Path | None = None) -> None:
        self.engine = engine or DeepResearchEngine()
        self.eval_path = eval_path or project_root() / "data" / "eval_set_deterministic.jsonl"

    def load_cases(self, limit: int | None = None) -> list[dict]:
        cases: list[dict] = []
        with self.eval_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                cases.append(json.loads(line))
                if limit and len(cases) >= limit:
                    break
        return cases

    def run(self, limit: int | None = 5) -> dict:
        results: list[EvaluationResult] = []
        for case in self.load_cases(limit=limit):
            state = self.engine.run(topic=case["topic"], depth_level=case.get("depth_level", 2))
            if state.evaluation:
                results.append(state.evaluation)
        if not results:
            return {}
        bad_case_categories = Counter()
        for result in results:
            bad_case_categories.update(result.bad_case_categories)

        return {
            "cases": len(results),
            "avg_task_success_rate": round(sum(r.task_success_rate for r in results) / len(results), 3),
            "avg_citation_accuracy": _mean_optional([r.citation_accuracy for r in results]),
            "avg_citation_resolution_rate": round(
                sum(r.citation_resolution_rate for r in results) / len(results), 3
            ),
            "avg_critic_catch_rate": round(sum(r.critic_catch_rate for r in results) / len(results), 3),
            "avg_answer_relevance": _mean_optional([r.answer_relevance for r in results]),
            "avg_faithfulness": _mean_optional([r.faithfulness for r in results]),
            "avg_latency_seconds": round(sum(r.latency_seconds for r in results) / len(results), 3),
            "avg_cost_usd": round(sum(r.cost_usd for r in results) / len(results), 4),
            "avg_token_used": round(sum(r.token_used for r in results) / len(results), 3),
            "bad_case_categories": dict(bad_case_categories),
        }


def load_metric_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _mean_optional(values: list[float | None]) -> float | None:
    numeric_values = [value for value in values if value is not None]
    if not numeric_values:
        return None
    return round(sum(numeric_values) / len(numeric_values), 3)


def compare_metric_summaries(
    current: dict[str, Any],
    baseline: dict[str, Any],
    quality_drop_threshold: float = 0.001,
    bad_case_increase_threshold: int = 0,
) -> dict[str, Any]:
    metric_diffs: dict[str, dict[str, Any]] = {}
    failures: list[str] = []

    for key in (*QUALITY_METRICS, *OPERATIONAL_METRICS):
        current_value = _numeric(current.get(key))
        baseline_value = _numeric(baseline.get(key))
        delta = round(current_value - baseline_value, 4)
        gated = key in QUALITY_METRICS
        status = "pass"
        if gated and delta < -quality_drop_threshold:
            status = "fail"
            failures.append(f"{key} dropped by {abs(delta):.4f}")
        metric_diffs[key] = {
            "baseline": baseline_value,
            "current": current_value,
            "delta": delta,
            "gated": gated,
            "status": status,
        }

    bad_case_diffs = _compare_bad_cases(
        current.get("bad_case_categories", {}),
        baseline.get("bad_case_categories", {}),
    )
    total_bad_case_delta = sum(item["delta"] for item in bad_case_diffs.values())
    bad_case_status = "pass"
    if total_bad_case_delta > bad_case_increase_threshold:
        bad_case_status = "fail"
        failures.append(f"bad cases increased by {total_bad_case_delta}")

    return {
        "status": "fail" if failures else "pass",
        "quality_drop_threshold": quality_drop_threshold,
        "bad_case_increase_threshold": bad_case_increase_threshold,
        "metrics": metric_diffs,
        "bad_case_categories": bad_case_diffs,
        "bad_case_status": bad_case_status,
        "failures": failures,
    }


def format_metric_comparison(comparison: dict[str, Any]) -> str:
    lines = [
        "Baseline comparison:",
        f"- status: {comparison['status']}",
        f"- quality_drop_threshold: {comparison['quality_drop_threshold']}",
    ]
    for key, diff in comparison["metrics"].items():
        gate = "gated" if diff["gated"] else "info"
        lines.append(
            f"- {key}: baseline={diff['baseline']} current={diff['current']} "
            f"delta={diff['delta']:+.4f} [{gate}/{diff['status']}]"
        )
    if comparison["bad_case_categories"]:
        lines.append("- bad_case_categories:")
        for key, diff in sorted(comparison["bad_case_categories"].items()):
            lines.append(
                f"  - {key}: baseline={diff['baseline']} current={diff['current']} "
                f"delta={diff['delta']:+d}"
            )
    if comparison["failures"]:
        lines.append("- failures:")
        for failure in comparison["failures"]:
            lines.append(f"  - {failure}")
    return "\n".join(lines)


def _numeric(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _compare_bad_cases(current: object, baseline: object) -> dict[str, dict[str, int]]:
    current_counts = current if isinstance(current, dict) else {}
    baseline_counts = baseline if isinstance(baseline, dict) else {}
    keys = set(current_counts) | set(baseline_counts)
    return {
        str(key): {
            "baseline": int(baseline_counts.get(key, 0)),
            "current": int(current_counts.get(key, 0)),
            "delta": int(current_counts.get(key, 0)) - int(baseline_counts.get(key, 0)),
        }
        for key in keys
    }
