"""Exercise the Tool lifecycle contract with local, bounded probes."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import tempfile
import threading
import warnings
from pathlib import Path
from typing import Any

from deepresearch_agent.mcp.client import MCPStdioClient
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    ERROR_RETRY_POLICIES,
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolErrorKind,
    ToolExecutionError,
)
from deepresearch_agent.tools.contract_adapter import SEARCH_TOOL_SPEC
from deepresearch_agent.workflow import DeepResearchEngine


def _error_kind_probe() -> int:
    exercised: set[ToolErrorKind] = set()
    for kind in ToolErrorKind:
        policies = dict(SEARCH_TOOL_SPEC.retry_policy)
        policies[kind] = ERROR_RETRY_POLICIES[kind].model_copy(
            update={"max_attempts": 1}
        )
        spec = SEARCH_TOOL_SPEC.model_copy(
            update={"name": f"error_probe_{kind.value}", "retry_policy": policies}
        )
        result = ReliableToolExecutor().execute(
            spec,
            lambda kind=kind: (_ for _ in ()).throw(
                ToolExecutionError(kind, f"probe:{kind.value}")
            ),
            RunToolContext(retry_budget=RetryBudget(max_retries=0)),
            degrade=True,
            degraded_value=[],
        )
        if result.error is not None and result.error.kind == kind:
            exercised.add(kind)
    return len(exercised)


def _timeout_overlap_probe() -> tuple[int, int]:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked() -> None:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=0.5)

    timeout_policy = dict(SEARCH_TOOL_SPEC.retry_policy)
    timeout_policy[ToolErrorKind.TIMEOUT] = ERROR_RETRY_POLICIES[
        ToolErrorKind.TIMEOUT
    ].model_copy(update={"max_attempts": 3, "base_backoff_s": 0.0})
    spec = SEARCH_TOOL_SPEC.model_copy(
        update={"timeout_s": 0.02, "total_timeout_s": 0.06, "retry_policy": timeout_policy}
    )
    try:
        result = ReliableToolExecutor(sleep=lambda _delay: None).execute(
            spec,
            blocked,
            RunToolContext(retry_budget=RetryBudget(max_retries=3)),
            degrade=True,
            degraded_value=[],
        )
    finally:
        release.set()
    if not entered.is_set() or result.error is None:
        return calls, result.attempts
    return calls, result.attempts


def _resource_warning_probe(repetitions: int = 6) -> int:
    server = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " m=json.loads(line); i=m.get('id'); method=m.get('method')\n"
        " if i is None: continue\n"
        " result=({'protocolVersion':'2025-06-18'} if method=='initialize' else {'tools':[]})\n"
        " print(json.dumps({'jsonrpc':'2.0','id':i,'result':result}),flush=True)\n"
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", ResourceWarning)
        for index in range(repetitions):
            client = MCPStdioClient(
                [sys.executable, "-c", server],
                server_name=f"lifecycle-{index}",
                request_timeout_s=2.0,
            )
            try:
                tools = client.connect()
                if tools:
                    raise AssertionError("probe server unexpectedly exposed tools")
            finally:
                client.close()
        gc.collect()
    return sum(issubclass(item.category, ResourceWarning) for item in captured)


class _BudgetProbeSearch:
    fidelity = "fixture"

    def search(
        self,
        _query: str,
        top_k: int = 3,
        source_type: str | None = None,
        *,
        context: RunToolContext | None = None,
    ) -> list[Any]:
        del top_k, source_type
        if context is None:
            raise AssertionError("workflow did not supply its run context")
        context.consume_external_request("search", tool="budget_probe")
        return []


def _budget_preservation_probe() -> bool:
    with tempfile.TemporaryDirectory(prefix="deepresearch-tool-lifecycle-") as tmp:
        engine = DeepResearchEngine(
            settings=Settings(
                storage_path=Path(tmp) / "probe.db",
                runs_root=Path(tmp) / "runs",
                max_external_search_requests_per_run=0,
                structured_logging_enabled=False,
                run_manifest_enabled=False,
                trajectory_record_enabled=False,
            ),
            search_tool=_BudgetProbeSearch(),
        )
        try:
            state = engine.run(topic="preserve completed planning on budget refusal", depth_level=1)
        finally:
            engine._checkpoint_conn.close()
    return bool(
        state.status == "budget_exceeded"
        and state.topic == "preserve completed planning on budget refusal"
        and state.plan is not None
        and state.todo_list
        and state.final_report
        and state.agent_decisions
    )


def measure() -> dict[str, int | bool]:
    calls, attempts = _timeout_overlap_probe()
    return {
        "tool_error_kinds_exercised": _error_kind_probe(),
        "timeout_operation_calls": calls,
        "timeout_attempts": attempts,
        "resource_warnings": _resource_warning_probe(),
        "budget_state_preserved": _budget_preservation_probe(),
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "tool_error_kinds_exercised": 7,
        "timeout_operation_calls": 1,
        "timeout_attempts": 1,
        "resource_warnings": 0,
        "budget_state_preserved": True,
    }
    return [
        f"{name}: expected {wanted!r}, got {metrics.get(name)!r}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("tool_lifecycle_self_test=FAIL production probe is dirty")
    cases = {
        "missing_error_kind": {**metrics, "tool_error_kinds_exercised": 6},
        "overlapping_retry": {**metrics, "timeout_operation_calls": 2},
        "resource_leak": {**metrics, "resource_warnings": 1},
        "state_lost": {**metrics, "budget_state_preserved": False},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"tool_lifecycle_self_test=FAIL accepted {label}")
    print(f"tool_lifecycle_self_test=PASS cases={len(cases) + 1}")


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
