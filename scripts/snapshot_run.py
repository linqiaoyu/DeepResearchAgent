from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("DEEPRESEARCH_SOURCE_ROOT", ROOT / "src")).resolve()
if str(SRC) not in os.sys.path:
    os.sys.path.insert(0, str(SRC))

from deepresearch_agent.schemas import ResearchState  # noqa: E402
from deepresearch_agent.settings import load_settings  # noqa: E402
from deepresearch_agent.workflow import DeepResearchEngine  # noqa: E402


DEFAULT_TOPICS = (
    "宁德时代 2024 年业绩与欧洲工厂扩张研究",
    "AI Agent 在财富管理行业的落地机会研究",
)
FIXED_AS_OF = "2026-07-09"
NODE_METHODS = (
    "_entry_node",
    "_planner_node",
    "_research_prepare_node",
    "_research_one_node",
    "_research_join_node",
    "_extractor_node",
    "_critic_node",
    "_retry_prepare_node",
    "_retry_one_node",
    "_retry_join_node",
    "_reporter_node",
    "_evaluator_node",
)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:/])/(?:[^/\s]+/)+[^/\s]+")
TIMESTAMP_KEYS = {
    "started_at",
    "timestamp",
    "updated_at",
    "created_at",
    "ended_at",
    "extracted_at",
    "captured_at",
}
LATENCY_KEYS = {"latency_ms", "latency_seconds", "elapsed_ms", "duration_ms"}
FLAG_FIELDS = {
    "TOOL_CONTRACT_ENABLED": "tool_contract_enabled",
    "INJECTION_GUARD_ENABLED": "injection_guard_enabled",
    "RUN_MANIFEST_ENABLED": "run_manifest_enabled",
    "CONTEXT_PACKER_ENABLED": "context_packer_enabled",
    "STRUCTURED_LOGGING_ENABLED": "structured_logging_enabled",
    "CONFIG_FAIL_FAST_ENABLED": "config_fail_fast_enabled",
    "STRUCTURED_OUTPUT_ENABLED": "structured_output_enabled",
    "PROGRESSIVE_DELIVERY_ENABLED": "progressive_delivery_enabled",
}


class SnapshotEngine(DeepResearchEngine):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.snapshot_node_events: list[dict[str, Any]] = []
        super().__init__(*args, **kwargs)


def _install_node_recorders() -> None:
    for method_name in NODE_METHODS:
        parent_method = getattr(DeepResearchEngine, method_name, None)
        if parent_method is None:
            continue

        def recorder(
            self: SnapshotEngine,
            graph_state: dict[str, Any],
            *,
            _method: Callable[..., Any] = parent_method,
            _name: str = method_name,
        ) -> Any:
            before = _graph_summary(graph_state)
            result = _method(self, graph_state)
            self.snapshot_node_events.append(
                {
                    "node": _name.removeprefix("_").removesuffix("_node"),
                    "input": before,
                    "output": _graph_summary(result),
                }
            )
            return result

        setattr(SnapshotEngine, method_name, recorder)


_install_node_recorders()


def build_snapshot(
    topic: str,
    *,
    depth_level: int = 1,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    os.environ["DEEPRESEARCH_MODE"] = "deterministic"
    os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_AS_OF"] = FIXED_AS_OF

    with tempfile.TemporaryDirectory(prefix="deepresearch-snapshot-") as temp_dir:
        temp_root = Path(temp_dir)
        settings = load_settings()
        replacements: dict[str, Any] = {
            "storage_path": temp_root / "snapshot.db",
            "execution_mode": "deterministic",
        }
        if hasattr(settings, "runs_root"):
            replacements["runs_root"] = runs_root or temp_root / "runs"
        settings = replace(settings, **replacements)
        engine = SnapshotEngine(settings=settings)
        state = engine.run(topic=topic, depth_level=depth_level)
        snapshot = _snapshot_payload(state, engine.snapshot_node_events, settings)
        engine._checkpoint_conn.close()
        return normalize(snapshot)


def _snapshot_payload(
    state: ResearchState,
    node_events: list[dict[str, Any]],
    settings: Any,
) -> dict[str, Any]:
    source_credibility = {source.url: source.credibility for source in state.sources}
    evidence_ids = {
        item.id: f"evidence-{index:03d}"
        for index, item in enumerate(
            sorted(state.evidence_store, key=lambda item: (item.sub_question_id, item.source_url, item.claim)),
            start=1,
        )
    }
    retry_ids = {
        item.id: f"retry-{index:03d}"
        for index, item in enumerate(
            sorted(state.retry_queue, key=lambda item: (item.sub_question_id or "", item.query, item.reason)),
            start=1,
        )
    }
    report_claims = _report_claims(state, evidence_ids)
    evaluation = state.evaluation.model_dump(mode="json") if state.evaluation else None
    if evaluation:
        evaluation.pop("research_id", None)
    payload = {
        "schema_version": 1,
        "topic": state.topic,
        "depth_level": state.depth_level,
        "status": state.status,
        "final_report": state.final_report or "",
        "report_footnote_evidence": {
            str(number): evidence_ids[evidence_id]
            for number, evidence_id in sorted(state.report_footnote_evidence.items())
            if evidence_id in evidence_ids
        },
        "report_claims": report_claims,
        "evidence": [
            {
                "id": evidence_ids[item.id],
                "sub_question_id": item.sub_question_id,
                "claim": item.claim,
                "claim_type": item.claim_type,
                "source_kind": item.source_kind,
                "source_url": item.source_url,
                "source_title": item.source_title,
                "source_pub_date": item.source_pub_date.isoformat(),
                "extract_text": item.extract_text,
                "credibility": source_credibility.get(item.source_url),
                "confidence": item.confidence,
                "captured_at": item.extracted_at.isoformat(),
                "numeric_fields": (
                    item.numeric_fields.model_dump(mode="json") if item.numeric_fields else None
                ),
            }
            for item in sorted(
                state.evidence_store,
                key=lambda item: (item.sub_question_id, item.source_url, item.claim),
            )
        ],
        "critic": (
            {
                "passed": state.critic_report.passed,
                "overall_quality": state.critic_report.overall_quality,
                "iteration": state.critic_report.iteration,
                "forced_pass": state.critic_report.forced_pass,
                "issues": [
                    {
                        "issue_type": issue.issue_type,
                        "severity": issue.severity,
                        "affected_claims": issue.affected_claims,
                        "message": issue.message,
                    }
                    for issue in state.critic_report.issues
                ],
            }
            if state.critic_report
            else None
        ),
        "retry_queue_events": [
            {
                "id": retry_ids[item.id],
                "reason": item.reason,
                "query": item.query,
                "source_type": item.source_type,
                "sub_question_id": item.sub_question_id,
                "severity": item.severity,
                "completed": item.completed,
            }
            for item in sorted(
                state.retry_queue,
                key=lambda item: (item.sub_question_id or "", item.query, item.reason),
            )
        ],
        "evaluation": evaluation,
        "node_summaries": sorted(
            node_events,
            key=lambda item: (
                item["node"],
                json.dumps(item["input"], ensure_ascii=False, sort_keys=True),
                json.dumps(item["output"], ensure_ascii=False, sort_keys=True),
            ),
        ),
        "side_effects": _side_effects(state, settings),
    }
    if state.structured_output is not None:
        payload["structured_output"] = state.structured_output.model_dump(mode="json")
    return payload


def _side_effects(state: ResearchState, settings: Any) -> dict[str, Any]:
    side_effects: dict[str, Any] = {
        "manifest_enabled": bool(getattr(settings, "run_manifest_enabled", False)),
        "context_events": list(state.metadata.get("context_events", [])),
        "degradation_events": list(state.metadata.get("degradation_events", [])),
        "tool_error_summary": dict(state.metadata.get("tool_error_summary", {})),
    }
    runs_root = getattr(settings, "runs_root", None)
    if runs_root:
        manifest_path = Path(runs_root) / state.research_id / "manifest.json"
        if manifest_path.exists():
            side_effects["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return side_effects


def _report_claims(
    state: ResearchState,
    evidence_ids: dict[str, str],
) -> list[dict[str, Any]]:
    report = state.final_report or ""
    claims: list[dict[str, Any]] = []
    section = ""
    for line in report.splitlines():
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue
        if not line.startswith("- "):
            continue
        referenced = []
        for match in re.findall(r"\[\^(\d+)\]", line):
            evidence_id = state.report_footnote_evidence.get(int(match))
            if evidence_id in evidence_ids:
                referenced.append(evidence_ids[evidence_id])
        claims.append(
            {
                "section": section,
                "text": re.sub(r"\s*\[\^\d+\]", "", line.removeprefix("- ")).strip(),
                "evidence_ids": referenced,
            }
        )
    return claims


def _graph_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    state_data = value.get("research_state", {})
    if hasattr(state_data, "model_dump"):
        state_data = state_data.model_dump(mode="json")
    summary: dict[str, Any] = {
        "phase": state_data.get("current_phase") if isinstance(state_data, dict) else None,
        "status": state_data.get("status") if isinstance(state_data, dict) else None,
        "source_count": len(state_data.get("sources", [])) if isinstance(state_data, dict) else 0,
        "evidence_count": (
            len(state_data.get("evidence_store", [])) if isinstance(state_data, dict) else 0
        ),
        "retry_count": len(state_data.get("retry_queue", [])) if isinstance(state_data, dict) else 0,
    }
    fanout_subq = value.get("fanout_sub_question")
    if isinstance(fanout_subq, dict):
        summary["sub_question_id"] = fanout_subq.get("id")
    fanout_retry = value.get("fanout_retry_task")
    if isinstance(fanout_retry, dict):
        summary["retry_query"] = fanout_retry.get("query")
    for key in (
        "research_sources",
        "research_records",
        "research_structured_evidence",
        "retry_sources",
        "retry_records",
    ):
        batches = value.get(key)
        if isinstance(batches, dict):
            summary[key] = {
                str(batch_key): len(batch_value) if isinstance(batch_value, list) else 1
                for batch_key, batch_value in sorted(batches.items())
            }
    return summary


def normalize(value: Any, *, key: str | None = None) -> Any:
    if key in TIMESTAMP_KEYS:
        return "<normalized-timestamp>"
    if key == "config_hash":
        return "<normalized-config-hash>"
    if key in LATENCY_KEYS:
        return 0
    if isinstance(value, dict):
        return {
            str(item_key): normalize(item_value, key=str(item_key))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            if item_key not in {"random_seed", "db_filename"}
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        normalized = UUID_RE.sub("<normalized-id>", value)
        normalized = ABSOLUTE_PATH_RE.sub("<normalized-path>", normalized)
        if normalized.endswith(".db"):
            return "<normalized-db>"
        return normalized
    return value


def encode_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(encode_snapshot(snapshot).encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic normalized workflow snapshot.")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(args.topic, depth_level=args.depth)
    output.write_text(encode_snapshot(snapshot), encoding="utf-8")
    print(f"snapshot={output}")
    print(f"sha256={snapshot_sha256(snapshot)}")


if __name__ == "__main__":
    main()
