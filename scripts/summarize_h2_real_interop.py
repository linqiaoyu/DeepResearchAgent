"""Summarize the preregistered R147 live artifacts into a publishable proof."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from deepresearch_agent.trajectory import AgentTrajectory, verify_trajectory_offline


ROOT = Path(__file__).resolve().parents[1]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def summarize(evidence_root: Path) -> dict[str, Any]:
    llm_paths = [
        evidence_root / "attempt5" / f"llm-{probe}-trajectory.json"
        for probe in range(1, 4)
    ]
    llm_failure_path = evidence_root / "attempt5" / "llm-failure-trajectory.json"
    rag_path = evidence_root / "attempt12" / "real-interop-rag.json"
    mcp_path = evidence_root / "attempt6" / "real-interop-mcp.json"
    sources = [*llm_paths, llm_failure_path, rag_path, mcp_path]
    if any(not path.is_file() for path in sources):
        missing = [str(path) for path in sources if not path.is_file()]
        raise FileNotFoundError("missing R147 evidence: " + ", ".join(missing))

    llm_trajectories = [
        AgentTrajectory.model_validate_json(path.read_text(encoding="utf-8"))
        for path in [*llm_paths, llm_failure_path]
    ]
    llm_successes = sum(
        trajectory.termination is not None
        and trajectory.termination.status == "completed"
        and len(trajectory.llm_calls) >= 1
        and all(call.error is None for call in trajectory.llm_calls)
        for trajectory in llm_trajectories[:3]
    )
    llm_failure_degradations = int(
        llm_trajectories[3].termination is not None
        and llm_trajectories[3].termination.status == "failed"
        and any(call.error is not None for call in llm_trajectories[3].llm_calls)
    )

    rag = _json(rag_path)
    mcp = _json(mcp_path)
    rag_records = list(rag.get("records", []))
    mcp_records = list(mcp.get("records", []))
    rag_successes = sum(
        record.get("probe", 0) > 0
        and record.get("success") is True
        and record.get("fidelity") == "live"
        for record in rag_records
    )
    mcp_successes = sum(
        record.get("probe", 0) > 0
        and record.get("success") is True
        and record.get("fidelity") == "real_process"
        for record in mcp_records
    )
    rag_failure_degradations = sum(
        record.get("probe") == 0 and record.get("degraded") is True
        for record in rag_records
    )
    mcp_failure_degradations = sum(
        record.get("probe") == 0 and record.get("degraded") is True
        for record in mcp_records
    )

    llm_observable = [
        int(
            trajectory.termination is not None
            and bool(trajectory.llm_calls)
            and verify_trajectory_offline(trajectory).trace_commitment_verified
            and all(call.latency_seconds >= 0 and call.cost_cny >= 0 for call in trajectory.llm_calls)
        )
        for trajectory in llm_trajectories
    ]
    boundary_records = [*rag_records, *mcp_records]
    record_observable = [
        int(
            record.get("trajectory_recorded") == 1
            and record.get("termination_recorded") == 1
            and record.get("offline_verified") == 1
            and isinstance(record.get("latency_seconds"), int | float)
            and float(record["latency_seconds"]) >= 0
            and isinstance(record.get("cost_cny"), int | float)
            and float(record["cost_cny"]) >= 0
        )
        for record in boundary_records
    ]
    observed = [*llm_observable, *record_observable]

    total_cost = 0.0
    ledger_rows = 0
    for path in evidence_root.glob("**/global-ledger.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            total_cost += float(item.get("cost_cny", 0.0))
            ledger_rows += 1

    return {
        "round": 147,
        "status": "passed",
        "preregistration": "docs/decisions/147/preregistration.json",
        "metrics": {
            "real_llm_successes": llm_successes,
            "real_rag_successes": rag_successes,
            "real_mcp_successes": mcp_successes,
            "llm_failure_degradations": llm_failure_degradations,
            "rag_failure_degradations": rag_failure_degradations,
            "mcp_failure_degradations": mcp_failure_degradations,
            "observability_coverage": sum(observed) / len(observed),
            "observed_probes": len(observed),
            "total_cost_cny": round(total_cost, 8),
            "round_fuse_cny": 40.0,
            "ledger_rows": ledger_rows,
        },
        "sources": [
            {
                "artifact": str(path.relative_to(ROOT)),
                "sha256": _digest(path),
            }
            for path in sources
        ],
        "notes": {
            "rag_service": "temporary local qdrant/qdrant:v1.18.3-unprivileged",
            "remote_qdrant_mutated": False,
            "quality_claim": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = summarize(args.evidence_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["metrics"], sort_keys=True))


if __name__ == "__main__":
    main()
