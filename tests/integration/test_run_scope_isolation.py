from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class RunScopeIsolationTests(unittest.TestCase):
    def test_one_engine_isolates_eight_concurrent_fixture_runs(self) -> None:
        topics = [f"并发运行作用域隔离 {index}" for index in range(8)]
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                branch_budget_enabled=True,
                branch_total_budget=3,
                branch_single_cap=2,
                dynamic_capability_enabled=False,
                max_critic_iter=1,
                structured_logging_enabled=False,
            )
            with DeepResearchEngine(settings=settings) as engine:
                serial = {
                    topic: engine.run(topic=topic, depth_level=1)
                    for topic in topics
                }
                with ThreadPoolExecutor(max_workers=8) as executor:
                    concurrent = dict(
                        zip(
                            topics,
                            executor.map(
                                lambda topic: engine.run(topic=topic, depth_level=1),
                                topics,
                            ),
                            strict=True,
                        )
                    )

        serial_snapshots = {
            topic: state.metadata["branch_budget"] for topic, state in serial.items()
        }
        concurrent_snapshots = {
            topic: state.metadata["branch_budget"]
            for topic, state in concurrent.items()
        }
        self.assertEqual(len({id(snapshot) for snapshot in concurrent_snapshots.values()}), 8)
        self.assertEqual(concurrent_snapshots, serial_snapshots)
        for topic in topics:
            self.assertEqual(concurrent[topic].status, "done")
            self.assertEqual(concurrent[topic].final_report, serial[topic].final_report)


if __name__ == "__main__":
    unittest.main()
