from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.mcp.server import (
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
    MCPResearchService,
    MCPServer,
    build_mcp_capability_registry,
    run_stdio,
)


class MCPServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="deepresearch-mcp-server-"
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.service = MCPResearchService(Path(self.temp_dir.name))
        self.registry = build_mcp_capability_registry(self.service)
        self.server = MCPServer(self.registry)

    def _initialize(self) -> dict[str, object]:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "unit-test-client",
                        "version": "1.0",
                    },
                },
            }
        )
        assert response is not None
        notification_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        self.assertIsNone(notification_response)
        return response

    def _call(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        request_id: object = 1,
    ) -> dict[str, object]:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        assert response is not None
        return response

    def test_initialize_negotiates_version_and_capabilities(self) -> None:
        response = self._initialize()
        self.assertEqual("init-1", response["id"])
        result = response["result"]
        assert isinstance(result, dict)
        self.assertEqual(MCP_PROTOCOL_VERSION, result["protocolVersion"])
        self.assertEqual(
            {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
            },
            result["capabilities"],
        )
        self.assertEqual(
            {"name": "deepresearch-agent", "version": "0.1.0"},
            result["serverInfo"],
        )

    def test_tools_list_mechanically_maps_registry_specs(self) -> None:
        self._initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }
        )
        assert response is not None
        tools = response["result"]["tools"]
        self.assertEqual(
            [
                "research.audit_export",
                "research.evidence",
                "research.snapshot_compare",
                "research.start",
            ],
            [item["name"] for item in tools],
        )
        for item in tools:
            metadata = self.registry.get(item["name"])
            self.assertEqual(
                metadata.tool_spec.input_schema,
                item["inputSchema"],
            )
            self.assertEqual(
                metadata.tool_spec.output_schema,
                item["outputSchema"],
            )
            self.assertEqual(
                not metadata.has_side_effect,
                item["annotations"]["readOnlyHint"],
            )

    def test_fixture_tool_call_runs_research_and_returns_evidence(
        self,
    ) -> None:
        self._initialize()
        run_response = self._call(
            "research.start",
            {
                "topic": "宁德时代 2024 年业绩与欧洲工厂扩张研究",
                "depth_level": 1,
            },
            request_id="run-1",
        )
        self.assertEqual("run-1", run_response["id"])
        run_result = run_response["result"]
        self.assertFalse(run_result["isError"])
        run_payload = run_result["structuredContent"]
        self.assertEqual("deterministic", run_payload["mode"])
        self.assertGreater(run_payload["evidence_count"], 0)
        self.assertGreater(run_payload["estimated_cost_cny"], 0.0)
        self.assertEqual(0.0, run_payload["real_api_cost_cny"])

        evidence_response = self._call(
            "research.evidence",
            {"research_id": run_payload["research_id"]},
            request_id="evidence-1",
        )
        evidence_result = evidence_response["result"]
        self.assertFalse(evidence_result["isError"])
        self.assertEqual(
            run_payload["evidence_count"],
            len(evidence_result["structuredContent"]["evidence"]),
        )

    def test_paid_execution_is_refused_without_explicit_confirmation(
        self,
    ) -> None:
        self._initialize()
        response = self._call(
            "research.start",
            {
                "topic": "fixture safety check",
                "execution_mode": "llm",
            },
        )
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn(
            "allow_paid=true",
            result["structuredContent"]["error"],
        )
        confirmed = self._call(
            "research.start",
            {
                "topic": "fixture safety check",
                "execution_mode": "llm",
                "allow_paid": True,
            },
        )
        confirmed_result = confirmed["result"]
        self.assertTrue(confirmed_result["isError"])
        self.assertIn(
            "disabled",
            confirmed_result["structuredContent"]["error"],
        )

    def test_audit_export_and_snapshot_compare_use_server_owned_runs(
        self,
    ) -> None:
        self._initialize()
        research_ids: list[str] = []
        for request_id in ("old", "new"):
            response = self._call(
                "research.start",
                {
                    "topic": "宁德时代 2024 年业绩与欧洲工厂扩张研究",
                    "depth_level": 1,
                },
                request_id=request_id,
            )
            research_ids.append(
                response["result"]["structuredContent"]["research_id"]
            )

        audit_response = self._call(
            "research.audit_export",
            {"research_id": research_ids[0]},
        )
        audit_payload = audit_response["result"]["structuredContent"]
        self.assertEqual("ok", audit_payload["citation_closure"])
        self.assertTrue(Path(audit_payload["artifact_path"]).is_dir())

        compare_response = self._call(
            "research.snapshot_compare",
            {
                "old_research_id": research_ids[0],
                "new_research_id": research_ids[1],
            },
        )
        compare_payload = compare_response["result"]["structuredContent"]
        self.assertEqual(
            "宁德时代 2024 年业绩与欧洲工厂扩张研究",
            compare_payload["question"],
        )

        arbitrary_path = self._call(
            "research.audit_export",
            {
                "research_id": research_ids[0],
                "output_path": "/tmp/caller-controlled",
            },
        )
        self.assertEqual(-32602, arbitrary_path["error"]["code"])

    def test_resources_and_prompts_probe_as_empty_lists(self) -> None:
        self._initialize()
        for method, key in (
            ("resources/list", "resources"),
            ("prompts/list", "prompts"),
        ):
            response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": method,
                    "method": method,
                    "params": {},
                }
            )
            assert response is not None
            self.assertEqual([], response["result"][key])

    def test_parse_error_uses_jsonrpc_code(self) -> None:
        response = self.server.handle_line("{not-json")
        assert response is not None
        self.assertEqual(-32700, response["error"]["code"])
        self.assertIsNone(response["id"])

    def test_invalid_request_uses_jsonrpc_code(self) -> None:
        response = self.server.handle_message(
            {"id": "bad", "method": "initialize", "params": {}}
        )
        assert response is not None
        self.assertEqual(-32600, response["error"]["code"])
        self.assertEqual("bad", response["id"])

    def test_unknown_method_uses_jsonrpc_code_and_preserves_id(
        self,
    ) -> None:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 42,
                "method": "unknown/method",
                "params": {},
            }
        )
        assert response is not None
        self.assertEqual(-32601, response["error"]["code"])
        self.assertEqual(42, response["id"])

    def test_missing_and_invalid_tool_params_use_invalid_params_code(
        self,
    ) -> None:
        self._initialize()
        for params in (
            {"arguments": {}},
            {"name": "research.evidence", "arguments": {}},
            {
                "name": "research.start",
                "arguments": {"topic": "", "unexpected": True},
            },
        ):
            response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "invalid",
                    "method": "tools/call",
                    "params": params,
                }
            )
            assert response is not None
            self.assertEqual(-32602, response["error"]["code"])
            self.assertEqual("invalid", response["id"])

    def test_stdio_is_line_delimited_and_notifications_have_no_response(
        self,
    ) -> None:
        requests = [
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-test", "version": "1"},
                },
            },
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": "notifications/initialized",
                "params": {},
            },
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        ]
        stdin = io.StringIO(
            "".join(
                json.dumps(item, ensure_ascii=False) + "\n"
                for item in requests
            )
        )
        stdout = io.StringIO()
        run_stdio(self.server, stdin, stdout)
        responses = [
            json.loads(line) for line in stdout.getvalue().splitlines()
        ]
        self.assertEqual([1, 2], [item["id"] for item in responses])


if __name__ == "__main__":
    unittest.main()
