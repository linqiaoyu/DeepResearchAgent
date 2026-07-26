from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deepresearch_agent import cli


class CliCostOutputTests(unittest.TestCase):
    def test_run_demo_labels_run_and_global_ledger_costs_separately(self) -> None:
        state = SimpleNamespace(
            research_id="run-031",
            current_phase="done",
            status="completed",
            final_report="# report",
            evaluation=None,
        )
        llm_client = Mock()
        llm_client.run_total_cny.return_value = 0.00592684
        llm_client.ledger_total_cny.return_value = 35.89842044
        engine = Mock()
        engine.run.return_value = state
        engine.llm_client = llm_client

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "report.md"
            argv = ["deepresearch-demo", "--output", str(output_path)]
            stdout = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(cli, "load_settings", return_value=object()),
                patch.object(cli, "DeepResearchEngine", return_value=engine),
                redirect_stdout(stdout),
            ):
                cli.run_demo()

            self.assertEqual(output_path.read_text(encoding="utf-8"), "# report")

        output = stdout.getvalue()
        self.assertIn("llm_run_total_cny=0.00592684", output)
        self.assertIn("llm_global_ledger_total_cny=35.89842044", output)
        self.assertNotIn("\nllm_ledger_total_cny=", output)
        llm_client.run_total_cny.assert_called_once_with("run-031")


if __name__ == "__main__":
    unittest.main()
