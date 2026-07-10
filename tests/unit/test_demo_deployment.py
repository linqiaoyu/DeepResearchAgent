from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from datetime import date
from pathlib import Path

from deepresearch_agent.api import main as api_main
from deepresearch_agent.api.demo import DailyCostGuard, DemoLimitExceeded, DemoService
from deepresearch_agent.settings import Settings


class DailyCostGuardTests(unittest.TestCase):
    def test_daily_guard_persists_spend_and_blocks_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "guard.json"
            guard = DailyCostGuard(
                state_path=path,
                limit_cny=1.0,
                today_func=lambda: date(2026, 7, 10),
            )

            first = guard.record_spend(0.4)
            self.assertEqual(first["spent_cny"], 0.4)
            second = DailyCostGuard(
                state_path=path,
                limit_cny=1.0,
                today_func=lambda: date(2026, 7, 10),
            )
            self.assertEqual(second.snapshot()["spent_cny"], 0.4)
            second.record_spend(0.6)

            with self.assertRaises(DemoLimitExceeded):
                second.assert_can_start()

    def test_daily_guard_rolls_over_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "guard.json"
            path.write_text('{"date": "2026-07-09", "spent_cny": 5.0}\n', encoding="utf-8")
            guard = DailyCostGuard(
                state_path=path,
                limit_cny=5.0,
                today_func=lambda: date(2026, 7, 10),
            )

            snapshot = guard.snapshot()

            self.assertEqual(snapshot["date"], "2026-07-10")
            self.assertEqual(snapshot["spent_cny"], 0.0)
            self.assertFalse(snapshot["blocked"])


@unittest.skipIf(api_main.app is None, "FastAPI is not installed")
class DemoAPITests(unittest.TestCase):
    def test_demo_showcase_and_guarded_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "demo").mkdir(parents=True)
            (root / "data" / "golden_set" / "v1").mkdir(parents=True)
            (root / "data" / "recordings" / "golden_v1").mkdir(parents=True)
            (root / "data" / "demo" / "g3_showcase.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-07-09",
                        "methodology": {"judge": "qwen3.7-plus"},
                        "summary": {"avg_weighted_score": 0.78},
                        "reports": [
                            {
                                "id": "Q01",
                                "topic": "demo topic",
                                "type": "财报解读",
                                "difficulty": "易",
                                "false_premise": False,
                                "metrics": {"weighted_score": 0.8},
                                "report_markdown": "# demo",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "golden_set" / "v1" / "questions.json").write_text(
                json.dumps(
                    {
                        "questions": [
                            {
                                "id": "Q01",
                                "topic": "demo topic",
                                "type": "财报解读",
                                "difficulty": "易",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            settings = Settings(
                storage_path=root / "data" / "runtime" / "research.db",
                demo_guard_path=root / "data" / "runtime" / "guard.json",
                demo_daily_llm_limit_cny=0.0,
            )
            original_service = api_main.demo_service
            api_main.demo_service = DemoService(settings=settings, root=root)
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Using `httpx` with `starlette.testclient` is deprecated.*",
                )
                from fastapi.testclient import TestClient

                client = TestClient(api_main.app)
            try:
                overview = client.get("/demo")
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(overview.json()["showcase_report_count"], 1)

                report = client.get("/demo/reports/Q01")
                self.assertEqual(report.status_code, 200)
                self.assertEqual(report.json()["report_markdown"], "# demo")

                rerun = client.post("/demo/rerun/Q01")
                self.assertEqual(rerun.status_code, 429)
                self.assertNotIn("DEEPSEEK", rerun.text)

                live = client.post("/demo/live", json={"topic": "demo", "depth_level": 1})
                self.assertEqual(live.status_code, 403)
                self.assertNotIn("DEMO_OWNER_TOKEN", live.text)
            finally:
                api_main.demo_service = original_service


if __name__ == "__main__":
    unittest.main()
