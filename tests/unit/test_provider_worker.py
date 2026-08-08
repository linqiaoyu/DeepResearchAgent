from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from scripts.check_provider_worker import counting_worker_loop, self_test

from deepresearch_agent.llm.client import _ProviderWorkerPool


def failing_start_loop(request_queue, response_queue, ready_queue) -> None:  # type: ignore[no-untyped-def]
    ready_queue.put(("error", "ImportError: no such provider sdk"))


def never_ready_loop(request_queue, response_queue, ready_queue) -> None:  # type: ignore[no-untyped-def]
    time.sleep(30)


def erroring_loop(request_queue, response_queue, ready_queue) -> None:  # type: ignore[no-untyped-def]
    ready_queue.put(("ok", None))
    while True:
        request = request_queue.get()
        if request is None:
            return
        if request.get("boom"):
            response_queue.put(("error", "RuntimeError: provider said no"))
            continue
        response_queue.put(("ok", {"echo": request.get("n"), "pid": os.getpid()}))


class ProviderWorkerPoolTests(unittest.TestCase):
    def test_sequential_calls_share_one_worker_process(self) -> None:
        """R091: one SDK import per run, not per call."""

        pool = _ProviderWorkerPool(worker_loop=counting_worker_loop)
        try:
            pids = {pool.call({"n": index}, timeout_seconds=10)["pid"] for index in range(4)}
        finally:
            pool.close()

        self.assertEqual(len(pids), 1)
        self.assertEqual(pool.spawns, 1)

    def test_a_provider_error_keeps_the_worker(self) -> None:
        """A refused request is not a hung transport; recycling would re-import."""

        pool = _ProviderWorkerPool(worker_loop=erroring_loop)
        try:
            first = pool.call({"n": 0}, timeout_seconds=10)["pid"]
            with self.assertRaisesRegex(RuntimeError, "provider said no"):
                pool.call({"boom": True}, timeout_seconds=10)
            second = pool.call({"n": 1}, timeout_seconds=10)["pid"]
        finally:
            pool.close()

        self.assertEqual(first, second)
        self.assertEqual(pool.spawns, 1)

    def test_an_overdue_call_terminates_and_replaces_its_worker(self) -> None:
        pool = _ProviderWorkerPool(worker_loop=counting_worker_loop)
        try:
            pool.call({"n": 0}, timeout_seconds=10)
            hung = next(iter(pool._workers.values()))
            hung_pid = hung.process.pid
            with self.assertRaisesRegex(TimeoutError, "provider subprocess terminated"):
                pool.call({"hang": True}, timeout_seconds=1.0)
            hung.process.join(timeout=5)

            self.assertFalse(hung.alive)
            self.assertNotIn(hung, pool._workers.values())

            replacement = pool.call({"n": 1}, timeout_seconds=10)
            self.assertEqual(replacement["echo"], 1)
            self.assertNotEqual(replacement["pid"], hung_pid)
            self.assertEqual(pool.spawns, 2)
        finally:
            pool.close()

    def test_worker_startup_has_its_own_budget(self) -> None:
        pool = _ProviderWorkerPool(worker_loop=never_ready_loop, startup_timeout_seconds=1.0)
        try:
            with self.assertRaisesRegex(TimeoutError, "did not become ready"):
                pool.call({"n": 0}, timeout_seconds=30)
        finally:
            pool.close()

    def test_a_worker_that_cannot_import_the_sdk_fails_loudly(self) -> None:
        pool = _ProviderWorkerPool(worker_loop=failing_start_loop)
        try:
            with self.assertRaisesRegex(RuntimeError, "failed to start"):
                pool.call({"n": 0}, timeout_seconds=10)
        finally:
            pool.close()

    def test_close_terminates_every_worker(self) -> None:
        pool = _ProviderWorkerPool(worker_loop=counting_worker_loop)
        pool.call({"n": 0}, timeout_seconds=10)
        worker = next(iter(pool._workers.values()))

        pool.close()
        worker.process.join(timeout=5)

        self.assertFalse(worker.alive)


class ProviderWorkerCheckCliTests(unittest.TestCase):
    def test_self_test_passes_on_the_current_implementation(self) -> None:
        self.assertEqual(self_test(), 0)

    def test_cli_runs_without_an_import_error(self) -> None:
        root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [sys.executable, "scripts/check_provider_worker.py", "--self-test"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("provider_worker_failures=0", completed.stdout)
        self.assertNotIn("ModuleNotFoundError", completed.stderr)


if __name__ == "__main__":
    unittest.main()
