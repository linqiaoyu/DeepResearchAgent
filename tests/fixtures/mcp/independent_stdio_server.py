"""Independent zero-dependency MCP stdio fixture used for interoperability."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


PROTOCOL_VERSION = "2025-06-18"


def _result(request_id: object, value: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _handle(
    message: dict[str, Any], server_id: str, *, bad_protocol: bool
) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": "1900-01-01" if bad_protocol else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"independent-{server_id}", "version": "1"},
            },
        )
    if method == "tools/list":
        return _result(
            request_id,
            {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Return the supplied value and server id.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "outputSchema": {"type": "object"},
                        "annotations": {
                            "readOnlyHint": True,
                            "idempotentHint": True,
                        },
                        "_meta": {
                            "deepresearch/costClass": "free",
                            "deepresearch/timeoutSeconds": 2,
                            "deepresearch/totalTimeoutSeconds": 4,
                            "deepresearch/toolVersion": "1",
                        },
                    }
                ]
            },
        )
    if method == "tools/call":
        params = message.get("params", {})
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        value = {"value": arguments.get("value"), "server": server_id}
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(value)}],
                "structuredContent": value,
                "isError": False,
            },
        )
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "Method not found"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--bad-protocol", action="store_true")
    parser.add_argument("--pid-file", type=Path)
    args = parser.parse_args()
    if args.pid_file is not None:
        args.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        response = _handle(message, args.server_id, bad_protocol=args.bad_protocol)
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
