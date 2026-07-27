from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKER = PROJECT_ROOT / "scripts" / "check_agent_guidance.py"


class AgentGuidanceTests(unittest.TestCase):
    def test_shared_guidance_contract_passes(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("agent_guidance_check=true", completed.stdout)

    def test_missing_claude_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "AGENTS.md").write_text(
                (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "CLAUDE.md").write_text(
                (PROJECT_ROOT / "CLAUDE.md")
                .read_text(encoding="utf-8")
                .replace("@AGENTS.md", ""),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(CHECKER), "--project-root", str(root)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("must import AGENTS.md", completed.stderr)

    def test_hard_coded_readme_test_count_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name in ("AGENTS.md", "CLAUDE.md", "README.md"):
                (root / name).write_text(
                    (PROJECT_ROOT / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            (root / "README.md").write_text("Ran 341 tests", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(CHECKER), "--project-root", str(root)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("must not hard-code a test count", completed.stderr)


if __name__ == "__main__":
    unittest.main()
