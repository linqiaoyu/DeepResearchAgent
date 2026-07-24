from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.mcp.client import (
    MCP_DISCOVERY_NODE_CONTRACT,
    ExternalMCPTool,
    MCPStdioClient,
)
from deepresearch_agent.schemas import ResearchState, SubQuestion
from deepresearch_agent.tools import (
    CapabilityRegistry,
    DeterministicCapabilitySelector,
)
from deepresearch_agent.tools.contracts import (
    ToolErrorKind,
    ToolSpec,
)
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolExecutionError,
)
from deepresearch_agent.trajectory import (
    TrajectoryRecorder,
    trajectory_recording,
)


class MCPClientEndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="deepresearch-mcp-client-"
        )
        self.addCleanup(self.temp_dir.cleanup)
        runtime_root = Path(self.temp_dir.name) / "runtime"
        environ = dict(os.environ)
        source_root = str(Path(__file__).resolve().parents[2] / "src")
        environ["PYTHONPATH"] = source_root
        self.client = MCPStdioClient(
            [
                sys.executable,
                "-m",
                "deepresearch_agent.mcp.server",
                "--runtime-root",
                str(runtime_root),
            ],
            server_name="self-fixture",
            request_timeout_s=10.0,
            environ=environ,
        )
        self.addCleanup(self.client.close)

    def test_discovers_registers_selects_and_calls_self_server(self) -> None:
        registry = CapabilityRegistry()
        state = ResearchState(topic="MCP 动态发现")
        recorder = TrajectoryRecorder(
            run_id=state.research_id,
            request={"topic": state.topic},
        )

        with trajectory_recording(recorder):
            decision = self.client.discover_and_register(
                registry,
                state,
                trusted_server=True,
                executor=ReliableToolExecutor(
                    sleep=lambda _seconds: None,
                ),
            )
            capability_name = "mcp.self-fixture.research.start"
            selector = DeterministicCapabilitySelector(
                registry,
                rules={"narrative": [capability_name]},
            )
            selection = selector.select(
                state,
                SubQuestion(
                    id="mcp-research",
                    question="分析本地 fixture",
                    search_queries=["fixture"],
                ),
            )
            tool = registry.resolve(capability_name)
            result = tool.call(
                {
                    "topic": "宁德时代 2024 年业绩与欧洲工厂扩张研究",
                    "depth_level": 1,
                    "execution_mode": "deterministic",
                    "allow_paid": False,
                },
                allow_paid=True,
            )

        self.assertEqual(
            [
                "mcp.self-fixture.research.audit_export",
                "mcp.self-fixture.research.evidence",
                "mcp.self-fixture.research.snapshot_compare",
                "mcp.self-fixture.research.start",
            ],
            [item.name for item in registry.query()],
        )
        self.assertEqual(
            "mcp_tool_discovery",
            decision.decision_type,
        )
        self.assertTrue(decision.inputs["trusted_annotations"])
        self.assertEqual(
            (capability_name,),
            selection.selected_capabilities,
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            0.0,
            result.value["real_api_cost_cny"],
        )
        self.assertEqual(
            "mcp",
            recorder.trajectory.tool_calls[-1].transport,
        )
        self.assertEqual(
            "self-fixture",
            recorder.trajectory.tool_calls[-1].server,
        )
        self.assertEqual(
            "mcp_tool_discovery",
            recorder.trajectory.agent_decisions[0].decision_type,
        )
        self.assertEqual(
            "mcp_tool_discovery",
            MCP_DISCOVERY_NODE_CONTRACT.name,
        )
        self.assertTrue(MCP_DISCOVERY_NODE_CONTRACT.decision_node)

    def test_untrusted_annotations_fail_closed(self) -> None:
        registry = CapabilityRegistry()
        state = ResearchState(topic="不可信注解")

        decision = self.client.discover_and_register(
            registry,
            state,
            trusted_server=False,
        )

        self.assertFalse(decision.inputs["trusted_annotations"])
        for metadata in registry.query():
            self.assertEqual("high", metadata.cost_level)
            self.assertTrue(metadata.has_side_effect)
            self.assertFalse(metadata.tool_spec.idempotent)

    def test_subprocess_response_timeout_is_bounded(self) -> None:
        client = MCPStdioClient(
            [
                sys.executable,
                "-c",
                (
                    "import sys,time;"
                    "sys.stdin.readline();"
                    "time.sleep(0.2)"
                ),
            ],
            server_name="silent",
            request_timeout_s=0.05,
        )
        try:
            with self.assertRaisesRegex(
                TimeoutError,
                "timed out after 0.05s",
            ):
                client.connect()
        finally:
            client.close()


class _FlakyClient:
    def __init__(self, failures: list[BaseException]) -> None:
        self.failures = list(failures)
        self.calls = 0

    def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        timeout_s: float,
    ) -> dict[str, object]:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {
            "name": name,
            "arguments": arguments,
            "timeout_s": timeout_s,
        }


def _external_tool(
    client: _FlakyClient,
    *,
    cost_class: str = "free",
) -> ExternalMCPTool:
    return ExternalMCPTool(
        client=client,
        remote_name="remote.echo",
        server_name="fake-server",
        spec=ToolSpec(
            name="mcp.fake.remote.echo",
            version="1",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_s=0.1,
            cost_class=cost_class,
            idempotent=True,
            has_side_effect=False,
        ),
        executor=ReliableToolExecutor(
            sleep=lambda _seconds: None,
            random_source=lambda: 0.5,
        ),
    )


class MCPExternalToolContractTest(unittest.TestCase):
    def test_transient_failure_retries_then_recovers(self) -> None:
        client = _FlakyClient(
            [
                ToolExecutionError(
                    ToolErrorKind.TRANSIENT,
                    "temporary failure",
                )
            ]
        )
        tool = _external_tool(client)
        context = RunToolContext(retry_budget=RetryBudget(max_retries=2))

        result = tool.call({"value": 1}, context=context)

        self.assertTrue(result.ok)
        self.assertEqual(2, result.attempts)
        self.assertEqual(2, client.calls)
        self.assertEqual(1, len(context.degradation_events))

    def test_timeout_retries_then_degrades(self) -> None:
        client = _FlakyClient(
            [TimeoutError("slow")] * 3
        )
        tool = _external_tool(client)
        context = RunToolContext(retry_budget=RetryBudget(max_retries=2))

        result = tool.call({"value": 1}, context=context)

        self.assertFalse(result.ok)
        self.assertTrue(result.degraded)
        self.assertEqual(ToolErrorKind.TIMEOUT, result.error.kind)
        self.assertEqual(3, result.attempts)
        self.assertEqual(
            {
                "status": "unavailable",
                "tool": "mcp.fake.remote.echo",
            },
            result.value,
        )

    def test_potentially_paid_tool_requires_explicit_confirmation(
        self,
    ) -> None:
        client = _FlakyClient([])
        tool = _external_tool(client, cost_class="high")

        result = tool.call({"value": 1}, allow_paid=False)

        self.assertFalse(result.ok)
        self.assertEqual(
            ToolErrorKind.BUDGET_EXCEEDED,
            result.error.kind,
        )
        self.assertIn("allow_paid=true", result.error.message)
        self.assertEqual(0, client.calls)


if __name__ == "__main__":
    unittest.main()
