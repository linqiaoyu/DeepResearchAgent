from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.mcp.server import MCP_PROTOCOL_VERSION
from deepresearch_agent.orchestration import (
    ContractField,
    DecisionGate,
    NodeContract,
)
from deepresearch_agent.schemas import AgentDecision, ResearchState
from deepresearch_agent.tools.capability_registry import (
    CapabilityMetadata,
    CapabilityRegistry,
)
from deepresearch_agent.tools.contracts import (
    ToolErrorKind,
    ToolResult,
    ToolSpec,
)
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolExecutionError,
)
from deepresearch_agent.trajectory import (
    ToolCallTrace,
    active_trajectory_recorder,
)


MCP_DISCOVERY_NODE_CONTRACT = NodeContract(
    name="mcp_tool_discovery",
    consumes={
        "research_state.agent_decisions": ContractField(list),
    },
    produces=frozenset({"research_state.agent_decisions"}),
    decision_node=True,
)


class MCPClientError(RuntimeError):
    pass


class MCPProtocolError(MCPClientError):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


@dataclass(frozen=True)
class DiscoveredMCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    annotations: dict[str, Any]
    metadata: dict[str, Any]


class MCPStdioClient:
    """Standard-library MCP client for a local stdio server subprocess."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        server_name: str,
        request_timeout_s: float = 10.0,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("MCP server command must not be empty")
        if request_timeout_s <= 0:
            raise ValueError("request_timeout_s must be positive")
        self.command = tuple(str(item) for item in command)
        self.server_name = server_name
        self.request_timeout_s = request_timeout_s
        self.environ = dict(os.environ if environ is None else environ)
        self.process: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._buffer = b""
        self._next_request_id = 1
        self._pending: dict[int | str | None, dict[str, Any]] = {}
        self.discovered_tools: tuple[DiscoveredMCPTool, ...] = ()

    def connect(self) -> tuple[DiscoveredMCPTool, ...]:
        if self.process is None:
            self._spawn()
        initialized = self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "deepresearch-agent",
                    "version": "0.1.0",
                },
            },
        )
        if initialized.get("protocolVersion") != MCP_PROTOCOL_VERSION:
            raise MCPClientError(
                "server did not negotiate MCP protocol 2025-06-18"
            )
        self._notify("notifications/initialized", {})
        listed = self._request("tools/list", {})
        raw_tools = listed.get("tools")
        if not isinstance(raw_tools, list):
            raise MCPClientError("tools/list result must contain a list")
        self.discovered_tools = tuple(
            self._parse_tool(item) for item in raw_tools
        )
        return self.discovered_tools

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> Any:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout_s=timeout_s,
        )
        if result.get("isError"):
            message = _tool_error_message(result)
            raise ToolExecutionError(ToolErrorKind.PERMANENT, message)
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and isinstance(
                first.get("text"),
                str,
            ):
                try:
                    return json.loads(first["text"])
                except json.JSONDecodeError:
                    return first["text"]
        return result

    def discover_and_register(
        self,
        registry: CapabilityRegistry,
        state: ResearchState,
        *,
        trusted_server: bool = False,
        executor: ReliableToolExecutor | None = None,
    ) -> AgentDecision:
        before = state.model_copy(deep=True)
        tools = self.connect()
        prefix = f"mcp.{_safe_name(self.server_name)}."
        registered_names = [prefix + item.name for item in tools]
        existing = {item.name for item in registry.query()}
        duplicates = sorted(existing.intersection(registered_names))
        if duplicates:
            raise ValueError(
                "MCP capability collision: " + ", ".join(duplicates)
            )
        for tool, capability_name in zip(
            tools,
            registered_names,
            strict=True,
        ):
            metadata = _capability_metadata(
                capability_name,
                tool,
                trusted_server=trusted_server,
            )
            registry.register(
                metadata,
                ExternalMCPTool(
                    client=self,
                    remote_name=tool.name,
                    server_name=self.server_name,
                    spec=metadata.tool_spec,
                    executor=executor,
                ),
            )

        decision = AgentDecision(
            decision_type="mcp_tool_discovery",
            made_by="MCPClient",
            inputs={
                "server": self.server_name,
                "discovered_tools": [item.name for item in tools],
                "registered_capabilities": registered_names,
                "trusted_annotations": trusted_server,
            },
            criterion=(
                "register every valid tools/list item in the existing "
                "CapabilityRegistry; accept annotations only for an "
                "explicitly trusted server"
            ),
            outcome=(
                f"registered={registered_names}; "
                f"trusted_annotations={trusted_server}"
            ),
            alternatives_considered=[
                "ignore discovered tools",
                "trust server annotations implicitly",
                "create a parallel tool registry",
            ],
        )
        record_agent_decision(state, decision)
        DecisionGate.validate(
            MCP_DISCOVERY_NODE_CONTRACT.name,
            {"research_state": before},
            {"research_state": state},
        )
        return decision

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if self._selector is not None:
            self._selector.close()
            self._selector = None
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        self.process = None

    def __enter__(self) -> MCPStdioClient:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.close()

    def _spawn(self) -> None:
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=self.environ,
        )
        if self.process.stdout is None:
            raise MCPClientError("MCP server stdout pipe is unavailable")
        self._selector = selectors.DefaultSelector()
        self._selector.register(
            self.process.stdout,
            selectors.EVENT_READ,
        )

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        response = self._response_for(
            request_id,
            timeout_s=timeout_s or self.request_timeout_s,
        )
        error = response.get("error")
        if isinstance(error, dict):
            raise MCPProtocolError(
                int(error.get("code", -32603)),
                str(error.get("message", "Unknown MCP error")),
                error.get("data"),
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise MCPClientError("MCP result must be an object")
        return result

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise MCPClientError("MCP server process is not connected")
        if process.poll() is not None:
            raise ConnectionError(
                f"MCP server exited with code {process.returncode}"
            )
        encoded = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        process.stdin.write(encoded + b"\n")
        process.stdin.flush()

    def _response_for(
        self,
        request_id: int | str | None,
        *,
        timeout_s: float,
    ) -> dict[str, Any]:
        pending = self._pending.pop(request_id, None)
        if pending is not None:
            return pending
        while True:
            response = self._read_response(timeout_s)
            response_id = response.get("id")
            if response_id == request_id:
                return response
            self._pending[response_id] = response

    def _read_response(self, timeout_s: float) -> dict[str, Any]:
        process = self.process
        if (
            process is None
            or process.stdout is None
            or self._selector is None
        ):
            raise MCPClientError("MCP server process is not connected")
        while b"\n" not in self._buffer:
            events = self._selector.select(timeout_s)
            if not events:
                raise TimeoutError(
                    f"MCP response timed out after {timeout_s:g}s"
                )
            chunk = os.read(process.stdout.fileno(), 65_536)
            if not chunk:
                stderr = _read_available_stderr(process)
                raise ConnectionError(
                    "MCP server closed stdout"
                    + (f": {stderr}" if stderr else "")
                )
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MCPClientError("invalid UTF-8 JSON-RPC response") from exc
        if not isinstance(value, dict):
            raise MCPClientError("JSON-RPC response must be an object")
        return value

    @staticmethod
    def _parse_tool(value: Any) -> DiscoveredMCPTool:
        if not isinstance(value, dict):
            raise MCPClientError("tools/list item must be an object")
        name = value.get("name")
        input_schema = value.get("inputSchema")
        if not isinstance(name, str) or not name:
            raise MCPClientError("discovered tool name must be non-empty")
        if not isinstance(input_schema, dict):
            raise MCPClientError(
                f"discovered tool {name} has no object inputSchema"
            )
        output_schema = value.get("outputSchema", {"type": "object"})
        annotations = value.get("annotations", {})
        metadata = value.get("_meta", {})
        return DiscoveredMCPTool(
            name=name,
            description=str(value.get("description", "")),
            input_schema=input_schema,
            output_schema=(
                output_schema
                if isinstance(output_schema, dict)
                else {"type": "object"}
            ),
            annotations=(
                annotations if isinstance(annotations, dict) else {}
            ),
            metadata=metadata if isinstance(metadata, dict) else {},
        )


class ExternalMCPTool:
    """Invoke one discovered MCP tool through the 010 reliability contract."""

    def __init__(
        self,
        *,
        client: Any,
        remote_name: str,
        server_name: str,
        spec: ToolSpec,
        executor: ReliableToolExecutor | None = None,
    ) -> None:
        self.client = client
        self.remote_name = remote_name
        self.server_name = server_name
        self.spec = spec
        self.executor = executor or ReliableToolExecutor()

    @property
    def may_charge(self) -> bool:
        return self.spec.cost_class != "free"

    def call(
        self,
        arguments: dict[str, Any],
        *,
        allow_paid: bool = False,
        context: RunToolContext | None = None,
        degrade: bool = True,
    ) -> ToolResult:
        run_context = context or RunToolContext(
            retry_budget=RetryBudget(max_retries=2)
        )

        def operation() -> Any:
            if self.may_charge and not allow_paid:
                raise ToolExecutionError(
                    ToolErrorKind.BUDGET_EXCEEDED,
                    "external MCP tool may charge; explicit "
                    "allow_paid=true is required",
                )
            return self.client.call_tool(
                self.remote_name,
                dict(arguments),
                timeout_s=self.spec.timeout_s,
            )

        result = self.executor.execute(
            self.spec,
            operation,
            run_context,
            degrade=degrade,
            degraded_value={
                "status": "unavailable",
                "tool": self.spec.name,
            },
            impact="external MCP tool output unavailable",
        )
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(
                ToolCallTrace(
                    tool_spec=self.spec.model_dump(mode="json"),
                    inputs=dict(arguments),
                    result=result.value,
                    error=(
                        result.error.model_dump(mode="json")
                        if result.error
                        else None
                    ),
                    attempts=result.attempts,
                    transport="mcp",
                    server=self.server_name,
                )
            )
        return result

    def __call__(self, arguments: dict[str, Any]) -> ToolResult:
        return self.call(arguments)


def _capability_metadata(
    capability_name: str,
    tool: DiscoveredMCPTool,
    *,
    trusted_server: bool,
) -> CapabilityMetadata:
    annotations = tool.annotations if trusted_server else {}
    metadata = tool.metadata if trusted_server else {}
    cost_level = str(metadata.get("deepresearch/costClass", "high"))
    if cost_level not in {"free", "low", "medium", "high"}:
        cost_level = "high"
    timeout_s = metadata.get("deepresearch/timeoutSeconds", 10.0)
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        timeout_s = 10.0
    version = metadata.get("deepresearch/toolVersion", "discovered")
    if not isinstance(version, str) or not version:
        version = "discovered"
    read_only = annotations.get("readOnlyHint") is True
    idempotent = annotations.get("idempotentHint") is True
    has_side_effect = not read_only
    spec = ToolSpec(
        name=capability_name,
        version=version,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        timeout_s=float(timeout_s),
        cost_class=cost_level,
        idempotent=idempotent,
        has_side_effect=has_side_effect,
    )
    return CapabilityMetadata(
        name=capability_name,
        applicable_subquestion_types=("*",),
        cost_level=cost_level,
        has_side_effect=has_side_effect,
        tool_spec=spec,
    )


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return safe or "external"


def _tool_error_message(result: dict[str, Any]) -> str:
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured.get("error"):
        return str(structured["error"])
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("text"):
            return str(first["text"])
    return "external MCP tool returned isError=true"


def _read_available_stderr(
    process: subprocess.Popen[bytes],
) -> str:
    if process.stderr is None:
        return ""
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stderr, selectors.EVENT_READ)
        if not selector.select(0):
            return ""
        return os.read(process.stderr.fileno(), 4096).decode(
            "utf-8",
            errors="replace",
        ).strip()
    finally:
        selector.close()
