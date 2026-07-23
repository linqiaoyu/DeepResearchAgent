from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import Field

from deepresearch_agent.schemas import StrictModel


class MetricDelta(StrictModel):
    metric: str
    left: float
    right: float
    delta: float
    verdict: Literal["显著改善", "噪声内", "显著回归"]


class OfflineOperationalMetrics(StrictModel):
    tool_error_rate: float = Field(ge=0, le=1)
    degradation_rate: float = Field(ge=0, le=1)
    context_overflow_rate: float = Field(ge=0, le=1)
    cost_cny_p50: float = Field(ge=0)
    cost_cny_p90: float = Field(ge=0)
    latency_seconds_p50: float = Field(ge=0)
    latency_seconds_p90: float = Field(ge=0)


def compare_result_payloads(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    significance_band: float = 0.01,
) -> list[MetricDelta]:
    left_metrics = _numeric_metrics(left.get("summary", left))
    right_metrics = _numeric_metrics(right.get("summary", right))
    rows: list[MetricDelta] = []
    for metric in sorted(set(left_metrics) & set(right_metrics)):
        left_value = left_metrics[metric]
        right_value = right_metrics[metric]
        delta = right_value - left_value
        direction = -1 if _lower_is_better(metric) else 1
        effective_delta = delta * direction
        if effective_delta > significance_band and not math.isclose(
            effective_delta,
            significance_band,
            abs_tol=1e-12,
        ):
            verdict = "显著改善"
        elif effective_delta < -significance_band and not math.isclose(
            effective_delta,
            -significance_band,
            abs_tol=1e-12,
        ):
            verdict = "显著回归"
        else:
            verdict = "噪声内"
        rows.append(
            MetricDelta(
                metric=metric,
                left=left_value,
                right=right_value,
                delta=round(delta, 6),
                verdict=verdict,
            )
        )
    return rows


def calculate_offline_metrics(
    trace_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
) -> OfflineOperationalMetrics:
    tool_calls = [row for row in trace_rows if row.get("event") == "tool_call"]
    tool_errors = [row for row in tool_calls if row.get("ok") is False]
    degradations = [
        row
        for row in trace_rows
        if row.get("event") == "degradation" or bool(row.get("degraded"))
    ]
    context_events = [
        row
        for row in trace_rows
        if row.get("event") == "context_event" or "dropped_count" in row
    ]
    overflows = [row for row in context_events if int(row.get("dropped_count", 0)) > 0]
    costs = [_nonnegative(row.get("cost_cny", 0.0)) for row in ledger_rows]
    latencies = [_nonnegative(row.get("latency_seconds", 0.0)) for row in ledger_rows]
    return OfflineOperationalMetrics(
        tool_error_rate=_rate(len(tool_errors), len(tool_calls)),
        degradation_rate=_rate(len(degradations), len(tool_calls)),
        context_overflow_rate=_rate(len(overflows), len(context_events)),
        cost_cny_p50=_percentile(costs, 0.5),
        cost_cny_p90=_percentile(costs, 0.9),
        latency_seconds_p50=_percentile(latencies, 0.5),
        latency_seconds_p90=_percentile(latencies, 0.9),
    )


def validate_golden_schema(
    questions_payload: dict[str, Any],
    revisions_payload: dict[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    questions = questions_payload.get("questions")
    if not isinstance(questions, list):
        return ["questions must be a list"]
    question_by_id: dict[str, dict[str, Any]] = {}
    required_question_fields = {
        "id",
        "type",
        "difficulty",
        "topic",
        "time_anchor",
        "structured_data_required",
        "gold",
        "freeze_status",
    }
    for question in questions:
        if not isinstance(question, dict):
            issues.append("question entry must be an object")
            continue
        qid = str(question.get("id", "<missing>"))
        question_by_id[qid] = question
        missing = sorted(required_question_fields - set(question))
        if missing:
            issues.append(f"{qid}: missing question fields {missing}")
        gold = question.get("gold", {})
        slots = gold.get("must_include", []) if isinstance(gold, dict) else []
        if not isinstance(slots, list):
            issues.append(f"{qid}: gold.must_include must be a list")
            continue
        for index, slot in enumerate(slots, 1):
            if not isinstance(slot, dict):
                issues.append(f"{qid}s{index}: slot must be an object")
                continue
            for field in ("fact", "value", "source", "tol", "w", "source_ref"):
                if field not in slot or slot[field] in (None, ""):
                    issues.append(f"{qid}s{index}: missing {field}")
            source_ref = slot.get("source_ref", {})
            if not isinstance(source_ref, dict):
                issues.append(f"{qid}s{index}: source_ref must be an object")
            else:
                for field in ("source_title", "source_url", "source_kind", "extract_text"):
                    if not source_ref.get(field):
                        issues.append(f"{qid}s{index}: source_ref missing {field}")
    if revisions_payload:
        issues.extend(_validate_shared_facts(question_by_id, revisions_payload))
    return issues


def _validate_shared_facts(
    questions: dict[str, dict[str, Any]],
    revisions: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    for group in revisions.get("shared_fact_groups", []):
        name = str(group.get("name", "unnamed"))
        slot_keys = [str(item) for item in group.get("slots", [])]
        fields = [str(item) for item in group.get("match_fields", ["value", "source_ref"])]
        resolved: list[dict[str, Any]] = []
        for slot_key in slot_keys:
            qid, separator, slot_text = slot_key.partition("s")
            if not separator or not slot_text.isdigit() or qid not in questions:
                issues.append(f"{name}: invalid slot reference {slot_key}")
                continue
            slots = questions[qid].get("gold", {}).get("must_include", [])
            slot_index = int(slot_text) - 1
            if slot_index < 0 or slot_index >= len(slots):
                issues.append(f"{name}: missing slot {slot_key}")
                continue
            resolved.append(slots[slot_index])
        if len(resolved) != len(slot_keys) or not resolved:
            continue
        for field in fields:
            values = [slot.get(field) for slot in resolved]
            if any(value != values[0] for value in values[1:]):
                issues.append(f"{name}: shared slots differ on {field}")
    return issues


def _numeric_metrics(value: Any, prefix: str = "") -> dict[str, float]:
    metrics: dict[str, float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            metrics.update(_numeric_metrics(item, path))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        metrics[prefix] = float(value)
    return metrics


def _lower_is_better(metric: str) -> bool:
    lowered = metric.lower()
    return any(
        token in lowered
        for token in ("cost", "latency", "error_rate", "overflow_rate", "uncited_claim_rate")
    )


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def _percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 6)


def _nonnegative(value: Any) -> float:
    return max(0.0, float(value or 0.0))
