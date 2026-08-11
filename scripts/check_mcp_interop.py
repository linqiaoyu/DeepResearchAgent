"""Exercise three MCP stdio processes through ToolSpec, budget, and trajectory."""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import warnings

from deepresearch_agent.mcp.client import MCPStdioClient
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import CapabilityRegistry, RunToolContext
from deepresearch_agent.trajectory import TrajectoryRecorder, trajectory_recording
from deepresearch_agent.workflow import DeepResearchEngine


ROOT = Path(__file__).resolve().parents[1]
INDEPENDENT_SERVER = ROOT / "tests/fixtures/mcp/independent_stdio_server.py"


def _probe(
    *,
    command: list[str],
    server_name: str,
    remote_tool_name: str,
    arguments: dict[str, Any],
    trusted: bool,
) -> dict[str, int]:
    environ = dict(os.environ)
    environ["PYTHONPATH"] = str(ROOT / "src")
    client = MCPStdioClient(
        command,
        server_name=server_name,
        request_timeout_s=20.0,
        environ=environ,
    )
    registry = CapabilityRegistry()
    state = ResearchState(topic=f"MCP probe {server_name}")
    recorder = TrajectoryRecorder(run_id=state.research_id, request={})
    process = None
    spec_count = 0
    budget_count = 0
    result_ok = 0
    try:
        with trajectory_recording(recorder):
            client.discover_and_register(registry, state, trusted_server=trusted)
            process = client.process
            metadata = registry.get(f"mcp.{server_name}.{remote_tool_name}")
            spec = metadata.tool_spec
            spec_count = int(
                spec.timeout_s > 0
                and spec.total_timeout_s is not None
                and spec.total_timeout_s >= spec.timeout_s
            )
            context = RunToolContext.for_run(max_external_fetch_requests=1)
            result = registry.resolve(metadata.name).call(
                arguments,
                allow_paid=True,
                context=context,
            )
            result_ok = int(result.ok)
            budget_count = int(
                context.external_request_budget.accepted_by_tool
                .get(metadata.name, {})
                .get("fetch", 0)
                == 1
            )
    finally:
        client.close()
    trajectory_count = int(
        len(recorder.trajectory.tool_calls) == 1
        and recorder.trajectory.tool_calls[0].transport == "mcp"
        and recorder.trajectory.tool_calls[0].server == server_name
    )
    closed = int(
        client.process is None
        and process is not None
        and process.poll() is not None
    )
    return {
        "success": result_ok,
        "tool_spec": spec_count,
        "budget": budget_count,
        "trajectory": trajectory_count,
        "closed": closed,
    }


def _abnormal_engine_probe(root: Path) -> tuple[int, int]:
    pid_file = root / "abnormal.pid"
    commands = json.dumps(
        [
            {
                "name": "bad-protocol",
                "command": [
                    sys.executable,
                    str(INDEPENDENT_SERVER),
                    "--server-id",
                    "bad-protocol",
                    "--bad-protocol",
                    "--pid-file",
                    str(pid_file),
                ],
                "timeout_s": 2,
            }
        ]
    )
    engine = DeepResearchEngine(
        settings=Settings(
            storage_path=root / "abnormal.db",
            runs_root=root / "runs",
            mcp_client_enabled=True,
            mcp_server_commands=commands,
            structured_logging_enabled=False,
        )
    )
    try:
        failed = int(
            engine.mcp_registration["connected"] == []
            and len(engine.mcp_registration["failed"]) == 1
        )
    finally:
        engine.close()
    pid = int(pid_file.read_text(encoding="utf-8"))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        residual = 0
    else:
        residual = 1
    return failed, residual


def measure() -> dict[str, int | float]:
    with tempfile.TemporaryDirectory() as directory, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        root = Path(directory)
        probes = [
            _probe(
                command=[
                    sys.executable,
                    "-m",
                    "deepresearch_agent.mcp.server",
                    "--runtime-root",
                    str(root / "project-server"),
                ],
                server_name="project-server",
                remote_tool_name="research.start",
                arguments={
                    "topic": "MCP interoperability control probe",
                    "depth_level": 1,
                    "execution_mode": "deterministic",
                    "allow_paid": False,
                },
                trusted=True,
            ),
            _probe(
                command=[
                    sys.executable,
                    str(INDEPENDENT_SERVER),
                    "--server-id",
                    "external-one",
                ],
                server_name="external-one",
                remote_tool_name="echo",
                arguments={"value": "one"},
                trusted=True,
            ),
            _probe(
                command=[
                    sys.executable,
                    str(INDEPENDENT_SERVER),
                    "--server-id",
                    "external-two",
                ],
                server_name="external-two",
                remote_tool_name="echo",
                arguments={"value": "two"},
                trusted=True,
            ),
        ]
        abnormal_degraded, abnormal_residual = _abnormal_engine_probe(root)
        gc.collect()
    return {
        "successful_stdio_probes": sum(item["success"] for item in probes),
        "independent_server_probes": 2,
        "tool_spec_coverage": sum(item["tool_spec"] for item in probes) / len(probes),
        "budget_coverage": sum(item["budget"] for item in probes) / len(probes),
        "trajectory_coverage": sum(item["trajectory"] for item in probes) / len(probes),
        "closed_processes": sum(item["closed"] for item in probes),
        "residual_processes": sum(1 - item["closed"] for item in probes),
        "abnormal_exit_degraded": abnormal_degraded,
        "abnormal_exit_residual_processes": abnormal_residual,
        "resource_warnings": sum(
            issubclass(item.category, ResourceWarning) for item in caught
        ),
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "successful_stdio_probes": 3,
        "independent_server_probes": 2,
        "tool_spec_coverage": 1.0,
        "budget_coverage": 1.0,
        "trajectory_coverage": 1.0,
        "closed_processes": 3,
        "residual_processes": 0,
        "abnormal_exit_degraded": 1,
        "abnormal_exit_residual_processes": 0,
        "resource_warnings": 0,
    }
    return [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("mcp_interop_self_test=FAIL production probe is dirty")
    mutations = {
        "two_processes": {**metrics, "successful_stdio_probes": 2},
        "only_self_server": {**metrics, "independent_server_probes": 0},
        "missing_spec": {**metrics, "tool_spec_coverage": 2 / 3},
        "budget_bypass": {**metrics, "budget_coverage": 2 / 3},
        "trajectory_bypass": {**metrics, "trajectory_coverage": 2 / 3},
        "residual_process": {**metrics, "residual_processes": 1},
        "abnormal_residual": {
            **metrics,
            "abnormal_exit_residual_processes": 1,
        },
        "resource_warning": {**metrics, "resource_warnings": 1},
    }
    for label, broken in mutations.items():
        if not evaluate(broken):
            raise SystemExit(f"mcp_interop_self_test=FAIL accepted {label}")
    print(f"mcp_interop_self_test=PASS cases={len(mutations) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
