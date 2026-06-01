from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path

from deepresearch_agent.api import main as api_main
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


@unittest.skipIf(api_main.app is None, "FastAPI is not installed")
class FastAPIContractTests(unittest.TestCase):
    def test_research_endpoints_match_readme_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "research.db"
            original_engine = api_main.engine
            api_main.engine = DeepResearchEngine(
                settings=Settings(storage_path=storage_path, max_critic_iter=1),
                store=SQLiteStore(storage_path),
            )
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Using `httpx` with `starlette.testclient` is deprecated.*",
                )
                from fastapi.testclient import TestClient

                client = TestClient(api_main.app)
            try:
                create_response = client.post(
                    "/research",
                    json={"topic": "fastapi contract smoke", "depth_level": 1},
                )
                self.assertEqual(create_response.status_code, 200)
                created = create_response.json()

                for key in ("research_id", "status", "current_phase", "report_url", "metrics"):
                    self.assertIn(key, created)
                self.assertEqual(created["status"], "done")
                self.assertEqual(created["current_phase"], "done")
                self.assertIsNotNone(created["metrics"])
                research_id = created["research_id"]

                state_response = client.get(f"/research/{research_id}")
                self.assertEqual(state_response.status_code, 200)
                state = state_response.json()
                self.assertEqual(state["research_id"], research_id)
                self.assertEqual(state["topic"], "fastapi contract smoke")
                self.assertEqual(state["status"], "done")
                self.assertGreater(len(state["evidence_store"]), 0)

                report_response = client.get(f"/research/{research_id}/report")
                self.assertEqual(report_response.status_code, 200)
                report = report_response.json()
                self.assertEqual(report["research_id"], research_id)
                self.assertIsInstance(report["report"], str)
                self.assertIn("# fastapi contract smoke", report["report"])

                metrics_response = client.get("/metrics")
                self.assertEqual(metrics_response.status_code, 200)
                metrics = metrics_response.json()
                self.assertIsInstance(metrics, list)
                self.assertGreaterEqual(len(metrics), 1)
                self.assertEqual(metrics[0]["research_id"], research_id)

                missing_response = client.get("/research/does-not-exist")
                self.assertEqual(missing_response.status_code, 404)
                self.assertEqual(missing_response.json()["detail"], "research_id not found")
            finally:
                api_main.engine = original_engine


if __name__ == "__main__":
    unittest.main()
