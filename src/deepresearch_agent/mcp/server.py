from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from deepresearch_agent.audit_bundle import export_audit_bundle
from deepresearch_agent.provenance import RunManifest, build_run_manifest
from deepresearch_agent.research_snapshot import (
    ResearchSnapshot,
    build_research_snapshot,
    diff_research_snapshots,
)
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.security import redact
from deepresearch_agent.settings import Settings, project_root
from deepresearch_agent.tools.capability_registry import (
    CapabilityMetadata,
    CapabilityRegistry,
)
from deepresearch_agent.tools.contracts import ToolSpec
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.tools.fixture_structured_data import (
    FixtureStructuredDataProvider,
)
from deepresearch_agent.workflow import DeepResearchEngine

# The target is the stable MCP specification revision named by its protocol
# date: https://modelcontextprotocol.io/specification/2025-06-18
MCP_PROTOCOL_VERSION = "2025-06-18"
JSONRPC_VERSION = "2.0"
SERVER_NAME = "deepresearch-agent"
SERVER_VERSION = "0.1.0"


class JSONRPCError(ValueError):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class ToolCallFailure(RuntimeError):
    """A domain failure returned as an MCP tool result, not a protocol error."""


@dataclass
class _RunRecord:
    state: ResearchState
    settings: Settings
    manifest: RunManifest
    snapshot: ResearchSnapshot
    audit_result: dict[str, Any] | None = None


class MCPResearchService:
    """Fixture-only implementations behind the MCP capability registry."""

    def __init__(self, runtime_root: Path | None = None) -> None:
        self.runtime_root = (
            runtime_root
            or project_root() / "data" / "runtime" / "mcp"
        )
        self._runs: dict[str, _RunRecord] = {}

    def start_research(self, arguments: dict[str, Any]) -> dict[str, Any]:
        execution_mode = str(
            arguments.get("execution_mode", "deterministic")
        )
        allow_paid = bool(arguments.get("allow_paid", False))
        if execution_mode != "deterministic":
            if not allow_paid:
                raise ToolCallFailure(
                    "paid execution requires explicit allow_paid=true"
                )
            raise ToolCallFailure(
                "paid execution is disabled on this fixture-only MCP server"
            )

        topic = str(arguments["topic"])
        depth_level = int(arguments.get("depth_level", 1))
        as_of = date.fromisoformat(
            str(arguments.get("as_of", "2026-07-09"))
        )
        settings = Settings(
            storage_path=self.runtime_root / "research.db",
            runs_root=self.runtime_root / "runs",
            execution_mode="deterministic",
            as_of=as_of,
            structured_logging_enabled=False,
        )
        engine = DeepResearchEngine(
            settings=settings,
            search_tool=FixtureSearchTool(),
            structured_data_provider=FixtureStructuredDataProvider(),
        )
        try:
            state = engine.run(topic=topic, depth_level=depth_level)
        finally:
            engine._checkpoint_conn.close()
        manifest = build_run_manifest(
            state,
            settings,
            started_at=state.started_at,
            ended_at=state.updated_at,
        )
        snapshot = build_research_snapshot(
            state=state,
            settings=settings,
            manifest=manifest,
            as_of=as_of,
        )
        self._runs[state.research_id] = _RunRecord(
            state=state,
            settings=settings,
            manifest=manifest,
            snapshot=snapshot,
        )
        return {
            "research_id": state.research_id,
            "status": state.status,
            "mode": settings.execution_mode,
            "evidence_count": len(state.evidence_store),
            "estimated_cost_cny": state.cost_used,
            "real_api_cost_cny": 0.0,
        }

    def get_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        record = self._record(str(arguments["research_id"]))
        return {
            "research_id": record.state.research_id,
            "evidence": [
                item.model_dump(mode="json")
                for item in record.state.evidence_store
            ],
        }

    def export_audit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        record = self._record(str(arguments["research_id"]))
        if record.audit_result is None:
            output_dir = (
                self.runtime_root
                / "artifacts"
                / record.state.research_id
                / "audit-bundle"
            )
            record.audit_result = export_audit_bundle(
                state=record.state,
                settings=record.settings,
                manifest=record.manifest,
                output_dir=output_dir,
            )
            record.audit_result["artifact_path"] = str(output_dir)
        return dict(record.audit_result)

    def compare_snapshots(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        old = self._record(str(arguments["old_research_id"])).snapshot
        new = self._record(str(arguments["new_research_id"])).snapshot
        result = diff_research_snapshots(old, new)
        return result.model_dump(mode="json")

    def _record(self, research_id: str) -> _RunRecord:
        try:
            return self._runs[research_id]
        except KeyError as exc:
            raise ToolCallFailure(
                f"unknown research_id: {research_id}"
            ) from exc


def build_mcp_capability_registry(
    service: MCPResearchService,
) -> CapabilityRegistry:
    """Declare MCP tools once, then mechanically expose their ToolSpec schema."""

    registry = CapabilityRegistry()
    definitions = (
        (
            CapabilityMetadata(
                name="research.start",
                applicable_subquestion_types=("*",),
                cost_level="low",
                has_side_effect=True,
                tool_spec=ToolSpec(
                    name="research.start",
                    version="1.0.0",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "minLength": 1},
                            "depth_level": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 3,
                                "default": 1,
                            },
                            "as_of": {
                                "type": "string",
                                "format": "date",
                                "default": "2026-07-09",
                            },
                            "execution_mode": {
                                "type": "string",
                                "enum": ["deterministic", "llm"],
                                "default": "deterministic",
                            },
                            "allow_paid": {
                                "type": "boolean",
                                "default": False,
                                "description": (
                                    "Explicit confirmation required before "
                                    "any paid execution."
                                ),
                            },
                        },
                        "required": ["topic"],
                        "additionalProperties": False,
                    },
                    output_schema={"type": "object"},
                    timeout_s=30.0,
                    cost_class="low",
                    idempotent=False,
                    has_side_effect=True,
                ),
            ),
            service.start_research,
        ),
        (
            CapabilityMetadata(
                name="research.evidence",
                applicable_subquestion_types=("verify",),
                cost_level="free",
                has_side_effect=False,
                tool_spec=ToolSpec(
                    name="research.evidence",
                    version="1.0.0",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "research_id": {
                                "type": "string",
                                "minLength": 1,
                            }
                        },
                        "required": ["research_id"],
                        "additionalProperties": False,
                    },
                    output_schema={"type": "object"},
                    timeout_s=5.0,
                    cost_class="free",
                    idempotent=True,
                    has_side_effect=False,
                ),
            ),
            service.get_evidence,
        ),
        (
            CapabilityMetadata(
                name="research.audit_export",
                applicable_subquestion_types=("verify",),
                cost_level="free",
                has_side_effect=True,
                tool_spec=ToolSpec(
                    name="research.audit_export",
                    version="1.0.0",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "research_id": {
                                "type": "string",
                                "minLength": 1,
                            }
                        },
                        "required": ["research_id"],
                        "additionalProperties": False,
                    },
                    output_schema={"type": "object"},
                    timeout_s=10.0,
                    cost_class="free",
                    idempotent=True,
                    has_side_effect=True,
                ),
            ),
            service.export_audit,
        ),
        (
            CapabilityMetadata(
                name="research.snapshot_compare",
                applicable_subquestion_types=("verify",),
                cost_level="free",
                has_side_effect=False,
                tool_spec=ToolSpec(
                    name="research.snapshot_compare",
                    version="1.0.0",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "old_research_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "new_research_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                        },
                        "required": [
                            "old_research_id",
                            "new_research_id",
                        ],
                        "additionalProperties": False,
                    },
                    output_schema={"type": "object"},
                    timeout_s=5.0,
                    cost_class="free",
                    idempotent=True,
                    has_side_effect=False,
                ),
            ),
            service.compare_snapshots,
        ),
    )
    for metadata, implementation in definitions:
        registry.register(metadata, implementation)
    return registry


_TOOL_DESCRIPTIONS = {
    "research.start": (
        "Run one local fixture-backed deterministic research workflow."
    ),
    "research.evidence": (
        "Return the evidence captured for a server-owned research run."
    ),
    "research.audit_export": (
        "Export a closed audit bundle to a server-owned artifact directory."
    ),
    "research.snapshot_compare": (
        "Compare snapshots from two server-owned research runs."
    ),
}


class MCPServer:
    """JSON-RPC 2.0 MCP server over UTF-8, line-delimited stdio."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self.initialized = False

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _error_response(None, -32700, "Parse error")
        return self.handle_message(message)

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        request_id: Any = (
            message.get("id") if isinstance(message, dict) else None
        )
        try:
            request_id, method, params, notification = _validate_request(
                message
            )
            if method in {"notifications/initialized", "initialized"}:
                self.initialized = True
                return None
            if notification:
                return None
            result = self._dispatch(method, params)
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": result,
            }
        except JSONRPCError as exc:
            return _error_response(
                request_id,
                exc.code,
                exc.message,
                exc.data,
            )

    def _dispatch(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        if method == "initialize":
            _validate_initialize_params(params)
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {},
                    "prompts": {},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            }
        if method == "tools/list":
            _require_initialized(self.initialized)
            if params:
                raise JSONRPCError(-32602, "Invalid params")
            return {"tools": self._tool_list()}
        if method == "tools/call":
            _require_initialized(self.initialized)
            return self._call_tool(params)
        if method == "resources/list":
            _require_initialized(self.initialized)
            if params:
                raise JSONRPCError(-32602, "Invalid params")
            return {"resources": []}
        if method == "prompts/list":
            _require_initialized(self.initialized)
            if params:
                raise JSONRPCError(-32602, "Invalid params")
            return {"prompts": []}
        raise JSONRPCError(-32601, "Method not found")

    def _tool_list(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for metadata in self.registry.query():
            spec = metadata.tool_spec
            tools.append(
                {
                    "name": metadata.name,
                    "description": _TOOL_DESCRIPTIONS.get(
                        metadata.name,
                        metadata.name,
                    ),
                    "inputSchema": spec.input_schema,
                    "outputSchema": spec.output_schema,
                    "annotations": {
                        "readOnlyHint": not metadata.has_side_effect,
                        "destructiveHint": False,
                        "idempotentHint": spec.idempotent,
                        "openWorldHint": False,
                    },
                    "_meta": {
                        "deepresearch/costClass": spec.cost_class,
                        "deepresearch/timeoutSeconds": spec.timeout_s,
                        "deepresearch/toolVersion": spec.version,
                    },
                }
            )
        return tools

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise JSONRPCError(-32602, "Invalid params")
        try:
            metadata = self.registry.get(name)
        except KeyError as exc:
            raise JSONRPCError(
                -32602,
                "Invalid params",
                {"tool": name, "reason": "unknown tool"},
            ) from exc
        _validate_schema(arguments, metadata.tool_spec.input_schema)
        implementation = self.registry.resolve(name)
        try:
            value = implementation(arguments)
        except ToolCallFailure as exc:
            return _tool_result(
                {"error": str(exc)},
                is_error=True,
            )
        return _tool_result(value)


def run_stdio(
    server: MCPServer,
    stdin: TextIO,
    stdout: TextIO,
    *,
    trace: TextIO | None = None,
) -> None:
    for raw_line in stdin:
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        _trace_stdio(trace, "CLIENT -> SERVER", line)
        response = server.handle_line(line)
        if response is None:
            _trace_stdio(trace, "SERVER -> CLIENT", "<no response>")
            continue
        encoded = json.dumps(
            response,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        _trace_stdio(trace, "SERVER -> CLIENT", encoded)
        stdout.write(encoded + "\n")
        stdout.flush()


def _validate_request(
    message: Any,
) -> tuple[Any, str, dict[str, Any], bool]:
    if not isinstance(message, dict):
        raise JSONRPCError(-32600, "Invalid Request")
    request_id = message.get("id")
    if (
        message.get("jsonrpc") != JSONRPC_VERSION
        or not isinstance(message.get("method"), str)
    ):
        raise JSONRPCError(-32600, "Invalid Request")
    if "id" in message and (
        isinstance(request_id, bool)
        or not isinstance(request_id, (str, int, type(None)))
    ):
        raise JSONRPCError(-32600, "Invalid Request")
    params = message.get("params", {})
    if not isinstance(params, dict):
        raise JSONRPCError(-32602, "Invalid params")
    return (
        request_id,
        str(message["method"]),
        params,
        "id" not in message,
    )


def _validate_initialize_params(params: dict[str, Any]) -> None:
    if not isinstance(params.get("protocolVersion"), str):
        raise JSONRPCError(-32602, "Invalid params")
    if not isinstance(params.get("capabilities"), dict):
        raise JSONRPCError(-32602, "Invalid params")
    client_info = params.get("clientInfo")
    if not isinstance(client_info, dict):
        raise JSONRPCError(-32602, "Invalid params")
    if not isinstance(client_info.get("name"), str) or not isinstance(
        client_info.get("version"),
        str,
    ):
        raise JSONRPCError(-32602, "Invalid params")


def _require_initialized(initialized: bool) -> None:
    if not initialized:
        raise JSONRPCError(
            -32600,
            "Invalid Request",
            {"reason": "initialize lifecycle incomplete"},
        )


def _validate_schema(
    value: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    required = schema.get("required", [])
    if not isinstance(required, list):
        raise JSONRPCError(-32602, "Invalid params")
    missing = [name for name in required if name not in value]
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise JSONRPCError(-32602, "Invalid params")
    unknown = (
        sorted(set(value) - set(properties))
        if schema.get("additionalProperties") is False
        else []
    )
    errors: list[str] = []
    if missing:
        errors.append("missing=" + ",".join(sorted(missing)))
    if unknown:
        errors.append("unknown=" + ",".join(unknown))
    for name, item in value.items():
        field_schema = properties.get(name)
        if not isinstance(field_schema, dict):
            continue
        expected = field_schema.get("type")
        if expected and not _matches_json_type(item, str(expected)):
            errors.append(f"{name}:expected {expected}")
            continue
        if "enum" in field_schema and item not in field_schema["enum"]:
            errors.append(f"{name}:not in enum")
        if isinstance(item, str) and len(item) < int(
            field_schema.get("minLength", 0)
        ):
            errors.append(f"{name}:shorter than minLength")
        if isinstance(item, int) and not isinstance(item, bool):
            if "minimum" in field_schema and item < int(
                field_schema["minimum"]
            ):
                errors.append(f"{name}:below minimum")
            if "maximum" in field_schema and item > int(
                field_schema["maximum"]
            ):
                errors.append(f"{name}:above maximum")
    if errors:
        raise JSONRPCError(
            -32602,
            "Invalid params",
            {"validation": errors},
        )


def _matches_json_type(value: Any, expected: str) -> bool:
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        ),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "null": value is None,
    }.get(expected, True)


def _tool_result(
    value: dict[str, Any],
    *,
    is_error: bool = False,
) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        ],
        "structuredContent": value,
        "isError": is_error,
    }


def _error_response(
    request_id: Any,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error,
    }


def _trace_stdio(
    trace: TextIO | None,
    direction: str,
    payload: str,
) -> None:
    if trace is None:
        return
    trace.write(f"{direction} {redact(payload)}\n")
    trace.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeepResearchAgent MCP server over line-delimited stdio."
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=None,
        help="Server-owned runtime directory; tool callers cannot override it.",
    )
    parser.add_argument(
        "--trace-file",
        type=Path,
        default=None,
        help=(
            "Operator-only redacted stdio trace. This path is never exposed "
            "through an MCP tool."
        ),
    )
    args = parser.parse_args()
    service = MCPResearchService(args.runtime_root)
    server = MCPServer(build_mcp_capability_registry(service))
    if args.trace_file is None:
        run_stdio(server, sys.stdin, sys.stdout)
        return
    args.trace_file.parent.mkdir(parents=True, exist_ok=True)
    with args.trace_file.open("a", encoding="utf-8") as trace:
        run_stdio(server, sys.stdin, sys.stdout, trace=trace)


if __name__ == "__main__":
    main()
