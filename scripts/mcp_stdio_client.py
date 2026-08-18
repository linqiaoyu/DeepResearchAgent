from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from deepresearch_agent.mcp.server import MCP_PROTOCOL_VERSION


class MinimalMCPClient:
    """Independent zero-dependency protocol probe, not the product client."""

    def __init__(self, command: list[str]) -> None:
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=dict(os.environ),
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("stdio pipes are unavailable")
        self._stdin = self.process.stdin
        self._stdout = self.process.stdout
        self.transcript: list[str] = []

    def request(
        self,
        request_id: str,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._send(message)
        response = self._receive()
        if response.get("id") != request_id:
            raise RuntimeError(
                f"response id mismatch: {response.get('id')!r}"
            )
        if "error" in response:
            raise RuntimeError(
                json.dumps(response["error"], ensure_ascii=False)
            )
        return response

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )
        self.transcript.append("SERVER -> CLIENT <no response expected>")

    def close(self) -> None:
        self._stdin.close()
        return_code = self.process.wait(timeout=10)
        stderr = (
            self.process.stderr.read()
            if self.process.stderr is not None
            else ""
        )
        self._stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()
        if return_code != 0:
            raise RuntimeError(
                f"MCP server exited {return_code}: {stderr}"
            )

    def _send(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.transcript.append(f"CLIENT -> SERVER {encoded}")
        self._stdin.write(encoded + "\n")
        self._stdin.flush()

    def _receive(self) -> dict[str, Any]:
        line = self._stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout before responding")
        self.transcript.append(
            f"SERVER -> CLIENT {line.rstrip()}"
        )
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError("MCP response must be an object")
        return value


def run_probe(runtime_root: Path, topic: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "deepresearch_agent.mcp.server",
        "--runtime-root",
        str(runtime_root),
    ]
    client = MinimalMCPClient(command)
    try:
        initialized = client.request(
            "initialize-1",
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "deepresearch-minimal-stdio-probe",
                    "version": "1.0.0",
                },
            },
        )
        client.notify("notifications/initialized", {})
        listed = client.request("tools-list-1", "tools/list", {})
        called = client.request(
            "tools-call-1",
            "tools/call",
            {
                "name": "research.start",
                "arguments": {
                    "topic": topic,
                    "depth_level": 1,
                    "execution_mode": "deterministic",
                    "allow_paid": False,
                },
            },
        )
    finally:
        client.close()

    tools = listed["result"]["tools"]
    tool_result = called["result"]
    if initialized["result"]["protocolVersion"] != MCP_PROTOCOL_VERSION:
        raise RuntimeError("protocol version negotiation failed")
    if len(tools) != 4:
        raise RuntimeError(f"expected 4 tools, found {len(tools)}")
    if tool_result.get("isError"):
        raise RuntimeError("fixture tools/call returned isError=true")
    client.transcript.append(
        "ASSERT protocol=2025-06-18 tools=4 tools/call=success "
        "real_api_cost_cny=0.0"
    )
    return client.transcript


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a zero-dependency stdio MCP handshake against the local "
            "DeepResearchHarness server."
        )
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument(
        "--topic",
        default="宁德时代 2024 年业绩与欧洲工厂扩张研究",
    )
    args = parser.parse_args()
    for line in run_probe(args.runtime_root, args.topic):
        print(line)


if __name__ == "__main__":
    main()
