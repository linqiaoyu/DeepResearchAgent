from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import warnings
from datetime import date
from pathlib import Path

from deepresearch_agent.api import main as api_main
from deepresearch_agent.api.demo import DailyCostGuard, DemoJobStore, DemoLimitExceeded, DemoQueueFull, DemoRunResult, DemoService
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


class DemoAsyncJobTests(unittest.TestCase):
    def test_rerun_enqueue_poll_and_complete_with_mock_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _demo_root(Path(tmp))
            started = threading.Event()
            release = threading.Event()

            def runner(question_id: str, topic: str) -> DemoRunResult:
                started.set()
                release.wait(timeout=5)
                return DemoRunResult(
                    research_id=f"research-{question_id}",
                    status="done",
                    report=f"# {topic}",
                    metrics={"token_used": 10},
                    cost_cny=0.25,
                    guard={},
                )

            service = _demo_service(root, runner_func=runner)
            first = service.rerun_golden("Q01")
            self.assertTrue(started.wait(timeout=2))
            running = service.job(first["job_id"])
            self.assertEqual(running["status"], "running")

            second = service.rerun_golden("Q01")
            queued = service.job(second["job_id"])
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(queued["queue_position"], 1)

            release.set()
            _wait_for(lambda: service.job(first["job_id"])["status"] == "done")
            _wait_for(lambda: service.job(second["job_id"])["status"] == "done")

            done = service.job(first["job_id"])
            self.assertEqual(done["result"]["research_id"], "research-Q01")
            self.assertEqual(done["result"]["cost_cny"], 0.25)

    def test_queue_limit_rejects_fourth_waiting_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _demo_root(Path(tmp))
            release = threading.Event()

            def runner(_question_id: str, _topic: str) -> DemoRunResult:
                release.wait(timeout=5)
                return DemoRunResult(
                    research_id="research",
                    status="done",
                    report="# done",
                    metrics={},
                    cost_cny=0.0,
                    guard={},
                )

            service = _demo_service(root, runner_func=runner, queue_limit=3)
            first = service.rerun_golden("Q01")
            _wait_for(lambda: service.jobs.store.next_queued() is None)
            second = service.rerun_golden("Q01")
            third = service.rerun_golden("Q01")
            fourth = service.rerun_golden("Q01")

            with self.assertRaises(DemoQueueFull):
                service.rerun_golden("Q01")

            release.set()
            for job in (first, second, third, fourth):
                _wait_for(lambda job_id=job["job_id"]: service.job(job_id)["status"] == "done")

    def test_job_store_marks_unfinished_jobs_interrupted_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            store = DemoJobStore(path)
            queued = store.create(question_id="Q01", topic="demo")
            running = store.create(question_id="Q02", topic="demo")
            store.mark_running(running["job_id"])

            restarted = DemoJobStore(path)

            self.assertEqual(restarted.get(queued["job_id"])["status"], "interrupted")
            self.assertEqual(restarted.get(running["job_id"])["status"], "interrupted")

    def test_guard_blocks_before_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _demo_root(Path(tmp))
            service = _demo_service(root, limit_cny=0.0)

            with self.assertRaises(DemoLimitExceeded):
                service.rerun_golden("Q01")

            self.assertEqual(service.jobs.store.queued_count(), 0)


def _demo_root(root: Path) -> Path:
    (root / "data" / "demo").mkdir(parents=True)
    (root / "data" / "golden_set" / "v1").mkdir(parents=True)
    (root / "data" / "recordings" / "golden_v1").mkdir(parents=True)
    (root / "data" / "demo" / "g3_showcase.json").write_text(
        json.dumps(
            {
                "as_of": "2026-07-09",
                "methodology": {"judge": "qwen3.7-plus"},
                "summary": {"avg_weighted_score": 0.78},
                "reports": [],
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
                    },
                    {
                        "id": "Q02",
                        "topic": "demo topic 2",
                        "type": "财报解读",
                        "difficulty": "易",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def _demo_service(
    root: Path,
    *,
    runner_func: object | None = None,
    limit_cny: float = 5.0,
    queue_limit: int = 3,
) -> DemoService:
    settings = Settings(
        storage_path=root / "data" / "runtime" / "research.db",
        demo_guard_path=root / "data" / "runtime" / "guard.json",
        demo_job_path=root / "data" / "runtime" / "jobs.json",
        demo_daily_llm_limit_cny=limit_cny,
        demo_queue_limit=queue_limit,
    )
    return DemoService(settings=settings, root=root, runner_func=runner_func)


def _wait_for(predicate: object, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


if __name__ == "__main__":
    unittest.main()
