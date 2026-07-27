from __future__ import annotations

import tempfile
import unittest
import warnings
from importlib import reload
from unittest.mock import patch
from pathlib import Path

from deepresearch_agent.api import main as api_main
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


@unittest.skipIf(api_main.app is None, "FastAPI is not installed")
class FastAPIContractTests(unittest.TestCase):
    def test_import_does_not_construct_engine_or_open_resources(self) -> None:
        fd_directory = Path("/dev/fd")
        before = len(list(fd_directory.iterdir())) if fd_directory.exists() else None
        with patch("deepresearch_agent.workflow.DeepResearchEngine") as engine_class:
            reload(api_main)
            engine_class.assert_not_called()
        reload(api_main)
        after = len(list(fd_directory.iterdir())) if fd_directory.exists() else None

        if before is not None and after is not None:
            self.assertEqual(before, after)

    def test_research_endpoints_match_readme_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "research.db"
            engine = DeepResearchEngine(
                settings=Settings(storage_path=storage_path, max_critic_iter=1),
                store=SQLiteStore(storage_path),
            )
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Using `httpx` with `starlette.testclient` is deprecated.*",
                )
                from fastapi.testclient import TestClient

                app = api_main.create_app(engine_factory=lambda: engine)
            token_patch = patch.dict("os.environ", {"DEMO_OWNER_TOKEN": "test-owner"})
            token_patch.start()
            try:
                with TestClient(app) as client:
                    healthz = client.get("/healthz")
                    self.assertEqual(healthz.status_code, 200)
                    self.assertEqual(healthz.json(), {"status": "ok"})
                    readyz = client.get("/readyz")
                    self.assertEqual(readyz.status_code, 200)
                    self.assertEqual(readyz.json(), {"status": "ready"})

                    create_response = client.post(
                        "/research",
                        json={"topic": "fastapi contract smoke", "depth_level": 1},
                        headers={"X-Demo-Owner-Token": "test-owner"},
                    )
                    self.assertEqual(create_response.status_code, 200)
                    created = create_response.json()

                    for key in ("research_id", "status", "current_phase", "report_url", "metrics"):
                        self.assertIn(key, created)
                    self.assertEqual(created["status"], "done")
                    self.assertEqual(created["current_phase"], "done")
                    self.assertIsNotNone(created["metrics"])
                    research_id = created["research_id"]

                    state_response = client.get(f"/research/{research_id}", headers={"X-Demo-Owner-Token": "test-owner"})
                    self.assertEqual(state_response.status_code, 200)
                    state = state_response.json()
                    self.assertEqual(state["research_id"], research_id)
                    self.assertEqual(state["topic"], "fastapi contract smoke")
                    self.assertEqual(state["status"], "done")
                    self.assertGreater(len(state["evidence_store"]), 0)

                    report_response = client.get(f"/research/{research_id}/report", headers={"X-Demo-Owner-Token": "test-owner"})
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

                    missing_response = client.get("/research/does-not-exist", headers={"X-Demo-Owner-Token": "test-owner"})
                    self.assertEqual(missing_response.status_code, 404)
                    self.assertEqual(missing_response.json()["detail"], "research_id not found")
            finally:
                token_patch.stop()


if __name__ == "__main__":
    unittest.main()
