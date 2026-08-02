from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


ROOT = Path(__file__).resolve().parents[2]


class StrictReplayCliTests(unittest.TestCase):
    def test_cli_strictly_replays_a_recorded_deterministic_run(self) -> None:
        """The CLI must replay an existing recorded trajectory without providers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                storage_path=root / "research.db",
                runs_root=root / "runs",
                trajectory_record_enabled=True,
                structured_logging_enabled=False,
                dynamic_capability_enabled=False,
                max_critic_iter=1,
            )
            with DeepResearchEngine(settings=settings) as engine:
                state = engine.run(topic="strict replay CLI guard", depth_level=1)
            trajectory = root / "runs" / state.research_id / "trajectory.json"
            environment = {**os.environ, "PYTHONPATH": "src"}
            result = subprocess.run(
                [sys.executable, "scripts/replay_trajectory.py", str(trajectory)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                check=False,
                text=True,
                stdin=subprocess.DEVNULL,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"status": "reproduced"', result.stdout)
        self.assertIn('"report.md": true', result.stdout)


if __name__ == "__main__":
    unittest.main()
