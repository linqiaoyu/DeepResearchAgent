from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from deepresearch_agent.api.demo import (
    DemoJobManager,
    DemoJobStore,
    DemoRunResult,
)
from deepresearch_agent.progressive_delivery import (
    ProgressiveDeliveryError,
    publish_report_progress,
    split_report_sections,
    validate_final_report,
)


REPORT = """# Demo

## 摘要
摘要 [^1]

## 详细分析
分析 [^1]

## 参考来源
[^1]: fixture source
"""


class ProgressiveDeliveryTests(unittest.TestCase):
    def test_sections_are_ordered_and_reassemble_byte_identically(self) -> None:
        sections = split_report_sections(REPORT)
        self.assertEqual(
            [item.heading for item in sections],
            ["front_matter", "摘要", "详细分析", "参考来源"],
        )
        self.assertEqual("".join(item.markdown for item in sections), REPORT)
        validate_final_report(REPORT, sections)

    def test_publish_failure_keeps_already_completed_sections(self) -> None:
        completed: list[str] = []

        def fail_on_detail(section: object) -> None:
            heading = getattr(section, "heading")
            if heading == "详细分析":
                raise RuntimeError("section sink unavailable")
            completed.append(heading)

        with self.assertRaisesRegex(
            RuntimeError,
            "section sink unavailable",
        ):
            publish_report_progress(REPORT, fail_on_detail)
        self.assertEqual(completed, ["front_matter", "摘要"])

    def test_final_validation_rejects_missing_reference(self) -> None:
        report = "# Demo\n\n## 摘要\n缺失 [^404]\n"
        with self.assertRaisesRegex(
            ProgressiveDeliveryError,
            "404",
        ):
            validate_final_report(report, split_report_sections(report))

    def test_polling_store_exposes_completed_sections_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DemoJobStore(Path(tmp) / "jobs.json")
            job = store.create(question_id="Q01", topic="demo")
            store.mark_running(job["job_id"])
            for section in split_report_sections(REPORT):
                store.mark_section(job["job_id"], section)
            store.mark_progress_validated(job["job_id"])
            payload = store.get(job["job_id"])

        progress = payload["progress"]
        self.assertEqual(
            [
                item["heading"]
                for item in progress["completed_sections"]
            ],
            ["front_matter", "摘要", "详细分析", "参考来源"],
        )
        self.assertEqual(progress["final_validation"], "passed")

    def test_enabled_job_manager_exposes_progress_and_preserves_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DemoJobStore(Path(tmp) / "jobs.json")
            manager = DemoJobManager(
                store=store,
                queue_limit=1,
                run_func=lambda _question_id, _topic: DemoRunResult(
                    research_id="research",
                    status="done",
                    report=REPORT,
                    metrics={},
                    cost_cny=0.0,
                    guard={},
                ),
                progressive_delivery_enabled=True,
            )
            job = manager.enqueue(question_id="Q01", topic="demo")
            deadline = time.time() + 2
            payload = manager.get(job["job_id"])
            while payload["status"] != "done" and time.time() < deadline:
                time.sleep(0.01)
                payload = manager.get(job["job_id"])

        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["result"]["report"], REPORT)
        self.assertEqual(
            payload["progress"]["final_validation"],
            "passed",
        )


if __name__ == "__main__":
    unittest.main()
