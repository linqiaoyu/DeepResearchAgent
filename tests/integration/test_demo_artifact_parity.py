from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DemoArtifactParityTest(unittest.TestCase):
    def test_deterministic_demo_reports_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            first = output_root / "first.md"
            second = output_root / "second.md"
            for output in (first, second):
                env = os.environ | {
                    "PYTHONPATH": str(ROOT / "src"),
                    "DEEPRESEARCH_STORAGE_PATH": str(
                        output.with_suffix(".db")
                    ),
                }
                subprocess.run(
                    [
                        os.sys.executable,
                        "scripts/run_demo.py",
                        "--output",
                        str(output),
                    ],
                    cwd=ROOT,
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
