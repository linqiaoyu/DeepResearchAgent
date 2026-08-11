"""Prove MCP collision, conservative trust, and Engine failure isolation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from deepresearch_agent.mcp.client import MCPStdioClient
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import CapabilityRegistry
from deepresearch_agent.workflow import DeepResearchEngine

from check_mcp_interop import measure as measure_interop


ROOT = Path(__file__).resolve().parents[1]
INDEPENDENT_SERVER = ROOT / "tests/fixtures/mcp/independent_stdio_server.py"


def _client(server_name: str, server_id: str) -> MCPStdioClient:
    return MCPStdioClient(
        [
            sys.executable,
            str(INDEPENDENT_SERVER),
            "--server-id",
            server_id,
        ],
        server_name=server_name,
        request_timeout_s=2,
    )


def _trust_and_collision() -> dict[str, int | float]:
    registry = CapabilityRegistry()
    first = _client("collision", "one")
    second = _client("collision", "two")
    try:
        first.discover_and_register(
            registry,
            ResearchState(topic="untrusted MCP"),
            trusted_server=False,
        )
        metadata = registry.get("mcp.collision.echo")
        conservative = int(
            metadata.cost_level == "high"
            and metadata.has_side_effect
            and metadata.tool_spec.cost_class == "high"
            and metadata.tool_spec.has_side_effect
            and not metadata.tool_spec.idempotent
        )
        paid_result = registry.resolve(metadata.name).call(
            {"value": "must not execute"},
            allow_paid=False,
        )
        paid_refused = int(not paid_result.ok and paid_result.attempts == 1)
        collision_rejected = 0
        try:
            second.discover_and_register(
                registry,
                ResearchState(topic="collision MCP"),
                trusted_server=False,
            )
        except ValueError:
            collision_rejected = 1
        return {
            "name_collision_rejection_rate": float(collision_rejected),
            "untrusted_conservative_contract": conservative,
            "untrusted_paid_call_refused": paid_refused,
            "registered_after_collision": len(registry.query()),
        }
    finally:
        first.close()
        second.close()


def _engine_failure_isolation(root: Path) -> dict[str, int | float]:
    baseline = DeepResearchEngine(
        settings=Settings(
            storage_path=root / "baseline.db",
            runs_root=root / "baseline-runs",
            structured_logging_enabled=False,
        )
    )
    try:
        local_names = {item.name for item in baseline.capability_registry.query()}
    finally:
        baseline.close()

    malformed = (
        "import sys;"
        "sys.stdin.readline();"
        "sys.stdout.write('not-json\\n');"
        "sys.stdout.flush();"
        "sys.stdin.read()"
    )
    timeout = "import sys,time;sys.stdin.readline();time.sleep(0.2);sys.stdin.read()"
    commands = json.dumps(
        [
            {
                "name": "malformed",
                "command": [sys.executable, "-c", malformed],
                "timeout_s": 0.2,
            },
            {
                "name": "timeout",
                "command": [sys.executable, "-c", timeout],
                "timeout_s": 0.05,
            },
            {
                "name": "crash",
                "command": [sys.executable, "-c", "raise SystemExit(3)"],
                "timeout_s": 0.2,
            },
        ]
    )
    engine = DeepResearchEngine(
        settings=Settings(
            storage_path=root / "failed.db",
            runs_root=root / "failed-runs",
            mcp_client_enabled=True,
            mcp_server_commands=commands,
            structured_logging_enabled=False,
        )
    )
    try:
        retained = {
            item.name
            for item in engine.capability_registry.query()
            if not item.name.startswith("mcp.")
        }
        failed = engine.mcp_registration["failed"]
        kinds = {str(item.get("error")) for item in failed}
        return {
            "explicit_mcp_failure_degradations": len(failed),
            "failure_kind_coverage": len(
                kinds & {"MCPClientError", "TimeoutError", "ConnectionError"}
            ),
            "local_capability_retention_rate": len(retained & local_names)
            / len(local_names),
            "mcp_capabilities_after_failures": len(
                [
                    item
                    for item in engine.capability_registry.query()
                    if item.name.startswith("mcp.")
                ]
            ),
        }
    finally:
        engine.close()


def measure() -> dict[str, int | float]:
    with tempfile.TemporaryDirectory() as directory:
        metrics = {
            **_trust_and_collision(),
            **_engine_failure_isolation(Path(directory)),
        }
    interop = measure_interop()
    metrics.update(
        {
            "successful_stdio_probes": interop["successful_stdio_probes"],
            "resource_warnings": interop["resource_warnings"],
        }
    )
    return metrics


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "name_collision_rejection_rate": 1.0,
        "untrusted_conservative_contract": 1,
        "untrusted_paid_call_refused": 1,
        "registered_after_collision": 1,
        "explicit_mcp_failure_degradations": 3,
        "failure_kind_coverage": 3,
        "local_capability_retention_rate": 1.0,
        "mcp_capabilities_after_failures": 0,
        "successful_stdio_probes": 3,
        "resource_warnings": 0,
    }
    return [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("mcp_safety_self_test=FAIL production probe is dirty")
    mutations = {
        "collision_allowed": {**metrics, "name_collision_rejection_rate": 0.0},
        "trusted_annotations": {**metrics, "untrusted_conservative_contract": 0},
        "paid_executed": {**metrics, "untrusted_paid_call_refused": 0},
        "silent_failure": {**metrics, "explicit_mcp_failure_degradations": 2},
        "local_loss": {**metrics, "local_capability_retention_rate": 0.75},
        "partial_remote": {**metrics, "mcp_capabilities_after_failures": 1},
    }
    for label, broken in mutations.items():
        if not evaluate(broken):
            raise SystemExit(f"mcp_safety_self_test=FAIL accepted {label}")
    print(f"mcp_safety_self_test=PASS cases={len(mutations) + 1}")


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
