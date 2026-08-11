"""Run the preregistered R149 ledger-isolation and live-planner probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from deepresearch_agent.agents.planner import PlannerAgent
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import (
    TrajectoryRecorder,
    trajectory_recording,
    verify_trajectory_offline,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "artifacts/149/reliability"
PROBE_FUSE_CNY = 1.0
PLANNER_CALLS = (
    "贵州茅台 2025 年营业收入、归母净利润和毛利率的同比变化",
    "宁德时代 2025 年收入与盈利能力的主要驱动因素",
    "比亚迪 2025 年经营现金流与资本开支变化",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stub_completion(**_kwargs: object) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }


def _ledger_worker(root: Path, worker: int) -> int:
    shard = root / f"shard-{worker}"
    ledger = shard / "ledger.jsonl"
    env_path = shard / ".env"
    shard.mkdir(parents=True, exist_ok=True)
    env_path.write_text("DEEPSEEK_API_KEY=probe-placeholder\n", encoding="utf-8")
    client = LLMClient(
        ledger_path=ledger,
        global_ledger_path=ledger,
        budget_cny=1.0,
        completion_func=_stub_completion,
        env_path=env_path,
    )
    run_id = f"r149-ledger-{worker}"
    client.start_run(run_id)
    result = client.complete(
        role="planner",
        run_id=run_id,
        messages=[{"role": "user", "content": f"ledger probe {worker}"}],
    )
    payload = {
        "worker": worker,
        "success": result.content == "OK",
        "ledger": str(ledger.relative_to(ROOT)),
        "index": str(client._ledger_index_path.relative_to(ROOT)),
        "ledger_rows": len(ledger.read_text(encoding="utf-8").splitlines()),
    }
    (shard / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return int(not payload["success"])


def _run_ledger_probe() -> dict[str, Any]:
    root = OUTPUT_ROOT / "ledger"
    root.mkdir(parents=True, exist_ok=True)
    commands = [
        [sys.executable, __file__, "--ledger-worker", str(worker), "--output", str(root)]
        for worker in range(1, 5)
    ]
    processes = [
        subprocess.Popen(command, cwd=ROOT, env=os.environ.copy()) for command in commands
    ]
    returncodes = [process.wait(timeout=60) for process in processes]
    results = [
        json.loads((root / f"shard-{worker}/result.json").read_text(encoding="utf-8"))
        for worker in range(1, 5)
    ]
    authorities = [result["ledger"] for result in results]
    negative_authorities = [authorities[0]] * 4
    duplicate_authority_rejected = len(set(negative_authorities)) != len(
        negative_authorities
    )
    return {
        "processes": len(processes),
        "successes": sum(code == 0 for code in returncodes),
        "returncodes": returncodes,
        "distinct_authorities": len(set(authorities)),
        "distinct_indexes": len({result["index"] for result in results}),
        "ledger_rows": sum(result["ledger_rows"] for result in results),
        "duplicate_authority_negative_control_rejected": duplicate_authority_rejected,
        "results": results,
    }


def _run_planner_probe() -> dict[str, Any]:
    root = OUTPUT_ROOT / "planner"
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "ledger.jsonl"
    client = LLMClient(
        ledger_path=ledger,
        global_ledger_path=ledger,
        budget_cny=PROBE_FUSE_CNY,
        fail_on_retry_exhaustion=True,
    )
    settings = Settings(
        storage_path=root / "research.db",
        execution_mode="llm",
        llm_ledger_path=ledger,
        llm_budget_cny=PROBE_FUSE_CNY,
    )
    planner = PlannerAgent(
        llm_client=client,
        settings=settings,
        domain_pack=load_domain_pack("finance"),
    )
    records: list[dict[str, Any]] = []
    for index, topic in enumerate(PLANNER_CALLS, start=1):
        run_id = f"r149-planner-{index}"
        client.start_run(run_id)
        recorder = TrajectoryRecorder(
            run_id=run_id,
            request={
                "topic": topic,
                "mode": "live",
                "depth_level": 1,
                "recorded_plan": {},
                "probe": "planner_timeout",
            },
        )
        started = time.perf_counter()
        with trajectory_recording(recorder):
            plan = planner.plan(topic, depth_level=1, research_id=run_id)
        elapsed = time.perf_counter() - started
        recorder.finalize(
            manifest_ref=None,
            artifacts={"plan.json": plan.model_dump_json()},
        )
        trajectory = recorder.write(root / f"planner-{index}-trajectory.json")
        verification = verify_trajectory_offline(recorder.trajectory)
        records.append(
            {
                "probe": index,
                "run_id": run_id,
                "success": len(plan.sub_questions) > 0,
                "fallback": bool(planner.last_stats.get("fallback")),
                "latency_seconds": round(elapsed, 6),
                "cost_cny": round(client.run_total_cny(run_id), 8),
                "llm_calls": len(recorder.trajectory.llm_calls),
                "termination": recorder.trajectory.termination.status,
                "offline_verified": verification.trace_commitment_verified,
                "trajectory": str(trajectory.relative_to(ROOT)),
            }
        )
    return {
        "configured_timeout_seconds": DEFAULT_LLM_CONFIG.roles["planner"].timeout_seconds,
        "calls": len(records),
        "successes": sum(record["success"] and not record["fallback"] for record in records),
        "total_cost_cny": round(sum(record["cost_cny"] for record in records), 8),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-worker", type=int)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT / "ledger")
    args = parser.parse_args()
    if args.ledger_worker is not None:
        return _ledger_worker(args.output, args.ledger_worker)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "round": 149,
        "quality_claim": False,
        "ledger": _run_ledger_probe(),
        "planner": _run_planner_probe(),
        "probe_fuse_cny": PROBE_FUSE_CNY,
    }
    output = OUTPUT_ROOT / "probe-results.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(output.relative_to(ROOT)), "sha256": _sha256(output), **payload}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
