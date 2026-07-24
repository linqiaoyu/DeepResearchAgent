from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.mcp_stdio_client import run_probe


class MinimalMCPStdioClientTest(unittest.TestCase):
    def test_full_fixture_handshake_and_tool_call(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="deepresearch-mcp-probe-"
        ) as temp_dir:
            transcript = run_probe(
                Path(temp_dir),
                "宁德时代 2024 年业绩与欧洲工厂扩张研究",
            )
        joined = "\n".join(transcript)
        self.assertIn('"method":"initialize"', joined)
        self.assertIn('"method":"notifications/initialized"', joined)
        self.assertIn('"method":"tools/list"', joined)
        self.assertIn('"method":"tools/call"', joined)
        self.assertIn(
            "ASSERT protocol=2025-06-18 tools=4 tools/call=success",
            joined,
        )


if __name__ == "__main__":
    unittest.main()
