from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepresearch_agent.evaluation.core_guardrail import (
    GUARDRAIL_CASES,
    guardrail_contract_sha256,
    score_guardrail_report,
)
from deepresearch_agent.settings import load_settings, project_root
from deepresearch_agent.tools.disclosure_source import CninfoDisclosureSource
from deepresearch_agent.tools.tavily_search import TavilySearchProvider
from deepresearch_agent.tools.akshare_structured_data import (
    AKShareStructuredDataProvider,
)
from deepresearch_agent.workflow import DeepResearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the frozen 033 two-case live regression guardrail."
    )
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--output-root",
        default="_collab/033/guardrail",
    )
    parser.add_argument(
        "--max-run-cost-cny",
        type=float,
        default=2.0,
    )
    args = parser.parse_args()
    if args.max_run_cost_cny <= 0 or args.max_run_cost_cny > 2.0:
        raise SystemExit("max-run-cost-cny must be within (0, 2.0]")

    output_root = _resolve(args.output_root)
    output_dir = output_root / args.label
    if output_dir.exists():
        raise SystemExit(f"refusing to overwrite guardrail run: {output_dir}")
    output_dir.mkdir(parents=True)

    started_at = datetime.now(timezone.utc)
    commit = _git_commit()
    results: list[dict[str, Any]] = []
    for case in GUARDRAIL_CASES:
        results.append(
            _run_case(
                case=case,
                output_dir=output_dir,
                max_run_cost_cny=args.max_run_cost_cny,
                commit=commit,
            )
        )

    aggregate = {
        "schema_version": "033-guardrail-run-v1",
        "label": args.label,
        "guardrail_contract_sha256": guardrail_contract_sha256(),
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "cases": results,
        "correct_metrics": sum(int(item["correct_metrics"]) for item in results),
        "total_metrics": sum(int(item["total_metrics"]) for item in results),
        "hallucinated_number_count": sum(
            int(item["hallucinated_number_count"])
            for item in results
        ),
        "cost_cny": round(
            sum(float(item["cost_cny"]) for item in results),
            8,
        ),
        "duration_seconds": round(
            sum(float(item["duration_seconds"]) for item in results),
            3,
        ),
    }
    aggregate["passed"] = (
        aggregate["correct_metrics"] == aggregate["total_metrics"]
        and aggregate["hallucinated_number_count"] == 0
    )
    result_path = output_dir / "result.json"
    result_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"result={result_path}")


def _run_case(
    *,
    case: Any,
    output_dir: Path,
    max_run_cost_cny: float,
    commit: str,
) -> dict[str, Any]:
    case_dir = output_dir / case.slug
    case_dir.mkdir()
    settings = replace(
        load_settings(),
        storage_path=case_dir / "research.db",
        llm_ledger_path=case_dir / "llm_ledger.jsonl",
        runs_root=case_dir / "runs",
        execution_mode="llm",
        llm_budget_cny=max_run_cost_cny,
        trajectory_record_enabled=True,
        run_manifest_enabled=True,
    )
    engine = DeepResearchEngine(settings=settings)
    try:
        providers = _assert_live_purity(engine)
        started_at = datetime.now(timezone.utc)
        started_clock = time.perf_counter()
        state = engine.run(topic=case.topic, depth_level=1)
        duration_seconds = round(time.perf_counter() - started_clock, 3)
        ended_at = datetime.now(timezone.utc)
        report = state.final_report or ""
        (case_dir / "report.md").write_text(report, encoding="utf-8")
        score = score_guardrail_report(report, case)
        cost_cny = float(
            state.metadata.get("llm_run_total_cny")
            or engine.llm_client.run_total_cny(state.research_id)
            if engine.llm_client
            else 0.0
        )
        if cost_cny > max_run_cost_cny:
            raise RuntimeError(
                f"run cost {cost_cny:.8f} exceeded {max_run_cost_cny:.8f}"
            )
        trajectory = _trajectory(case_dir, state.research_id)
        result = {
            **score,
            "topic": case.topic,
            "run_id": state.research_id,
            "status": state.status,
            "phase": state.current_phase,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": duration_seconds,
            "cost_cny": round(cost_cny, 8),
            "commit": commit,
            "config": {
                "execution_mode": settings.execution_mode,
                "models": {
                    role: config.model
                    for role, config in engine.llm_client.config.roles.items()
                }
                if engine.llm_client
                else {},
                "dynamic_capability_enabled": (
                    settings.dynamic_capability_enabled
                ),
                "reflection_enabled": settings.reflection_enabled,
                "research_loop_enabled": settings.research_loop_enabled,
                "research_loop_max_iterations": (
                    settings.research_loop_max_iterations
                ),
                "prior_memory_enabled": settings.prior_memory_enabled,
                "trajectory_record_enabled": (
                    settings.trajectory_record_enabled
                ),
                "max_run_cost_cny": max_run_cost_cny,
            },
            "providers": providers,
            "llm_usage": state.metadata.get("llm_usage", {}),
            "external_requests": state.metadata.get(
                "external_request_budget",
                {},
            ),
            "authority_channel_calls": _authority_channel_calls(
                state,
                trajectory,
            ),
            "termination": trajectory.get("termination"),
        }
        (case_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        engine._checkpoint_conn.close()


def _assert_live_purity(engine: DeepResearchEngine) -> dict[str, str]:
    search = engine.capability_registry.resolve("web_search")
    search = getattr(search, "provider", search)
    structured = engine.capability_registry.resolve(
        "structured_data_provider"
    )
    structured = getattr(structured, "provider", structured)
    disclosure = engine.capability_registry.resolve("disclosure_source")
    checks = (
        (engine.llm_client is not None, "LLMClient"),
        (isinstance(search, TavilySearchProvider), "TavilySearchProvider"),
        (
            isinstance(structured, AKShareStructuredDataProvider),
            "AKShareStructuredDataProvider",
        ),
        (
            isinstance(disclosure, CninfoDisclosureSource),
            "CninfoDisclosureSource",
        ),
        (
            os.getenv("DEEPRESEARCH_SEARCH_RECORDING_MODE") == "live",
            "DEEPRESEARCH_SEARCH_RECORDING_MODE=live",
        ),
    )
    failures = [expected for ok, expected in checks if not ok]
    if failures:
        raise RuntimeError(
            "live provider purity check failed: " + ", ".join(failures)
        )
    return {
        "llm": type(engine.llm_client).__name__,
        "search": type(search).__name__,
        "structured_data": type(structured).__name__,
        "disclosure": type(disclosure).__name__,
        "search_recording_mode": "live",
    }


def _authority_channel_calls(
    state: Any,
    trajectory: dict[str, Any],
) -> dict[str, int]:
    requests = state.metadata.get("external_request_budget", {})
    accepted = requests.get("accepted_by_tool", {})
    disclosure = accepted.get("disclosure_source", {})
    structured_stats = state.metadata.get("structured_data_stats", {})
    tool_calls = trajectory.get("tool_calls", [])
    return {
        "cninfo_logical_calls": sum(
            1
            for item in tool_calls
            if item.get("tool_spec", {}).get("name")
            == "disclosure_source"
        ),
        "cninfo_http_search_requests": int(disclosure.get("search", 0)),
        "cninfo_http_fetch_requests": int(disclosure.get("fetch", 0)),
        "akshare_logical_requests": sum(
            1
            for item in tool_calls
            if item.get("tool_spec", {}).get("name")
            == "structured_data_provider"
        ),
        "akshare_requested_operations": sum(
            int(item.get("requests", 0))
            for item in structured_stats.values()
            if isinstance(item, dict)
        ),
        "tavily_search_requests": int(requests.get("search_requests", 0)),
        "tavily_fetch_requests": int(requests.get("fetch_requests", 0)),
    }


def _trajectory(case_dir: Path, run_id: str) -> dict[str, Any]:
    path = case_dir / "runs" / run_id / "trajectory.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root() / path


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    main()
