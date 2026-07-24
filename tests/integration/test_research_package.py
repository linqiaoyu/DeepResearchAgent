from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_research_package.py"


class ResearchPackageTests(unittest.TestCase):
    def test_fixture_command_produces_complete_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "package"
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    str(SCRIPT),
                    "--topic",
                    "AI Agent 在财富管理行业的落地机会研究",
                    "--as-of",
                    "2026-07-09",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env=self._offline_env(),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("audit_citation_closure=ok", result.stdout)
            for relative in (
                "request.json",
                "report.md",
                "structured.json",
                "structured.md",
                "structured.xlsx",
                "research_snapshot.json",
                "audit_bundle/report.json",
                "audit_bundle/evidence.json",
                "audit_bundle/manifest.json",
            ):
                self.assertTrue((output / relative).is_file(), relative)

    def test_live_preflight_lists_all_requirements_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "must-not-exist"
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    str(SCRIPT),
                    "--topic",
                    "live preflight only",
                    "--as-of",
                    "2026-07-09",
                    "--output",
                    str(output),
                    "--mode",
                    "live",
                    "--env-path",
                    str(Path(tmp) / "absent.env"),
                ],
                cwd=ROOT,
                env=self._offline_env(),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("DEEPSEEK_API_KEY", result.stdout)
            self.assertIn("TAVILY_API_KEY", result.stdout)
            self.assertIn("--allow-paid-api", result.stdout)
            self.assertIn("single-digit CNY", result.stdout)
            self.assertFalse(output.exists())

    def _offline_env(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "TAVILY_API_KEY"}
        }
        env["PYTHONPATH"] = "src"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["STRUCTURED_LOGGING_ENABLED"] = "false"
        return env


if __name__ == "__main__":
    unittest.main()
