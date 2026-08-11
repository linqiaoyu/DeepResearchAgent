from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.observability import JsonLogger
from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow.engine import _build_engine_llm_client


class LLMLedgerRoutingTests(unittest.TestCase):
    def test_planner_transport_bound_covers_observed_sixty_second_timeouts(self) -> None:
        self.assertEqual(DEFAULT_LLM_CONFIG.roles["planner"].timeout_seconds, 180)

    def test_engine_configured_ledger_is_the_global_budget_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "isolated" / "ledger.jsonl"
            settings = Settings(
                storage_path=root / "research.db",
                execution_mode="llm",
                llm_ledger_path=ledger,
            )

            client = _build_engine_llm_client(settings, JsonLogger(enabled=False))

        self.assertEqual(client.ledger_path, ledger)
        self.assertEqual(client.global_ledger_path, ledger)
        self.assertEqual(client._ledger_index_path, ledger.with_suffix(".jsonl.index.json"))


if __name__ == "__main__":
    unittest.main()
