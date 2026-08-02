from __future__ import annotations

import argparse
import json
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
from deepresearch_agent.workflow import DeepResearchEngine
from run_agent_core_guardrail import (
    _assert_live_purity,
    _authority_channel_calls,
    _trajectory,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run one frozen live case twice on the same Engine to expose "
            "working, episodic, and procedural memory behavior."
        )
    )
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--output-root",
        default="_collab/033/memory_probe",
    )
    parser.add_argument("--max-run-cost-cny", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 < args.max_run_cost_cny <= 2.0:
        raise SystemExit("max-run-cost-cny must be within (0, 2.0]")

    output_root = _resolve(args.output_root)
    output_dir = output_root / args.label
    if output_dir.exists():
        raise SystemExit(f"refusing to overwrite memory probe: {output_dir}")
    output_dir.mkdir(parents=True)

    settings = replace(
        load_settings(),
        storage_path=output_dir / "research.db",
        llm_ledger_path=output_dir / "llm_ledger.jsonl",
        runs_root=output_dir / "runs",
        execution_mode="llm",
        llm_budget_cny=args.max_run_cost_cny,
        trajectory_record_enabled=True,
        run_manifest_enabled=True,
    )
    engine = DeepResearchEngine(settings=settings)
    try:
        providers = _assert_live_purity(engine)
        case = next(item for item in GUARDRAIL_CASES if item.slug == "moutai_600519")
        runs: list[dict[str, Any]] = []
        for ordinal in (1, 2):
            started_at = datetime.now(timezone.utc)
            started_clock = time.perf_counter()
            state = engine.run(topic=case.topic, depth_level=1)
            duration = round(time.perf_counter() - started_clock, 3)
            report = state.final_report or ""
            (output_dir / f"report_{ordinal}.md").write_text(
                report,
                encoding="utf-8",
            )
            trajectory = _trajectory(output_dir, state.research_id)
            cost = float(
                state.metadata.get("llm_run_total_cny")
                or engine.llm_client.run_total_cny(state.research_id)
                if engine.llm_client
                else 0.0
            )
            if cost > args.max_run_cost_cny:
                raise RuntimeError(
                    f"run cost {cost:.8f} exceeded {args.max_run_cost_cny:.8f}"
                )
            plan_queries = {
                item.id: list(item.search_queries)
                for item in state.plan.sub_questions
            } if state.plan else {}
            runs.append(
                {
                    "ordinal": ordinal,
                    "run_id": state.research_id,
                    "started_at": started_at.isoformat(),
                    "duration_seconds": duration,
                    "cost_cny": round(cost, 8),
                    "score": score_guardrail_report(report, case),
                    "plan_queries": plan_queries,
                    "component_activity": state.metadata.get(
                        "component_activity",
                        {},
                    ),
                    "authority_channel_calls": _authority_channel_calls(
                        state,
                        trajectory,
                    ),
                    "termination": trajectory.get("termination"),
                }
            )
        payload = {
            "schema_version": "033-memory-probe-v1",
            "label": args.label,
            "guardrail_contract_sha256": guardrail_contract_sha256(),
            "commit": _git_commit(),
            "providers": providers,
            "config": {
                "working_memory": settings.context_packer_enabled,
                "episodic_memory": settings.prior_memory_enabled,
                "procedural_memory": settings.procedural_memory_enabled,
                "reflection": settings.reflection_enabled,
            },
            "runs": runs,
        }
        (output_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        engine.close()


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
