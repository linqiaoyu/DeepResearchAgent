"""R123: the agent can consume an external MCP server's tools.

`mcp/server.py` exposes this agent as MCP tools and works. `mcp/client.py` --
including `discover_and_register`, which puts a remote tool behind the same
`ToolSpec`, budget and executor as every local capability -- was imported by
nothing outside its own package. The agent could not consume an external tool
and its capability set was the five hardcoded entries, whatever a server offered.

The fixture server here is this project's own MCP server, spawned over stdio,
which is a real server speaking the real protocol rather than a stub of it.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

SOURCE_ROOT = str(Path(__file__).resolve().parents[2] / "src")


def _server_spec(runtime_root: Path, *, name: str = "self-fixture") -> str:
    environ = dict(os.environ)
    environ["PYTHONPATH"] = SOURCE_ROOT
    return json.dumps(
        [
            {
                "name": name,
                "command": [
                    sys.executable,
                    "-m",
                    "deepresearch_agent.mcp.server",
                    "--runtime-root",
                    str(runtime_root),
                ],
                "environ": environ,
                "timeout_s": 20.0,
            }
        ]
    )


class MCPClientWiringTests(unittest.TestCase):
    def _engine(self, tmp: Path, *, enabled: bool, commands: str = "") -> DeepResearchEngine:
        return DeepResearchEngine(
            settings=Settings(
                storage_path=tmp / "research.db",
                runs_root=tmp / "runs",
                mcp_client_enabled=enabled,
                mcp_server_commands=commands,
                structured_logging_enabled=False,
            )
        )

    def test_an_external_server_contributes_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            engine = self._engine(
                tmp, enabled=True, commands=_server_spec(tmp / "runtime")
            )
            try:
                names = sorted(item.name for item in engine.capability_registry.query())
                registration = dict(engine.mcp_registration)
                remote = [name for name in names if name.startswith("mcp.")]
                specs = [
                    engine.capability_registry.get(name).tool_spec for name in remote
                ]
            finally:
                for client in engine.mcp_clients:
                    client.close()
                engine._checkpoint_conn.close()

        self.assertEqual(registration["failed"], [], registration)
        self.assertEqual(registration["connected"], ["self-fixture"])
        self.assertTrue(remote, f"no remote capability registered; saw {names}")
        for spec in specs:
            self.assertGreater(spec.timeout_s, 0)
            self.assertGreater(spec.total_timeout_s, 0)
            self.assertIn(spec.cost_class, {"free", "low", "medium", "high"})

    def test_the_flag_off_registers_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            engine = self._engine(
                tmp, enabled=False, commands=_server_spec(tmp / "runtime")
            )
            names = sorted(item.name for item in engine.capability_registry.query())
            registration = dict(engine.mcp_registration)
            engine._checkpoint_conn.close()

        self.assertEqual([name for name in names if name.startswith("mcp.")], [])
        self.assertFalse(registration["enabled"])
        self.assertEqual(registration["connected"], [])

    def test_an_unreachable_server_degrades_instead_of_ending_the_run(self) -> None:
        commands = json.dumps(
            [{"name": "missing", "command": [sys.executable, "-c", "raise SystemExit(3)"]}]
        )
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            engine = self._engine(tmp, enabled=True, commands=commands)
            registration = dict(engine.mcp_registration)
            names = sorted(item.name for item in engine.capability_registry.query())
            engine._checkpoint_conn.close()

        self.assertEqual(registration["connected"], [])
        self.assertEqual([item["server"] for item in registration["failed"]], ["missing"])
        self.assertIn("web_search", names, "the local capabilities were lost too")

    def test_invalid_configuration_is_recorded_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            engine = self._engine(tmp, enabled=True, commands="{not json")
            registration = dict(engine.mcp_registration)
            engine._checkpoint_conn.close()

        self.assertEqual(registration["connected"], [])
        self.assertEqual(registration["failed"][0]["server"], "<config>")


if __name__ == "__main__":
    unittest.main()
