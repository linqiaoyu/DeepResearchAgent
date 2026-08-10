"""A test that bounds a real clock from above is measuring the machine.

R114: `test_production_subprocess_timeout_terminates_worker` asserted a `spawn`
round trip finished inside a hard-coded 1.0s. Interpreter startup exceeded that
under full-suite load, the child was terminated before it ran a line of its
body, and the test failed reading a pid file that was never written -- 3/3
passing in isolation, red in a suite of 1078. Widening the constant would have
moved the threshold, not removed it.

The class is every upper bound on a clock-derived value under `tests/`, not the
one test that happened to fail first. These tests pin the scanner that
enumerates the class and the registry that keeps it from growing back.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_wall_clock_assertions as guard

ROOT = Path(__file__).resolve().parents[2]


class WallClockScannerTests(unittest.TestCase):
    def test_it_flags_a_bound_read_straight_off_the_clock(self) -> None:
        source = (
            "import time\n"
            "class T:\n"
            "    def test_x(self):\n"
            "        started = time.monotonic()\n"
            "        self.assertLess(time.monotonic() - started, 0.08)\n"
        )
        self.assertEqual(guard.scan_source(source, "probe.py"), {"probe.py::T.test_x": 1})

    def test_it_follows_the_clock_through_a_local(self) -> None:
        source = (
            "import time\n"
            "class T:\n"
            "    def test_x(self):\n"
            "        started = time.perf_counter()\n"
            "        elapsed = time.perf_counter() - started\n"
            "        self.assertLess(elapsed, 10.2)\n"
        )
        self.assertEqual(guard.scan_source(source, "probe.py"), {"probe.py::T.test_x": 1})

    def test_it_flags_an_elapsed_reported_by_the_code_under_test(self) -> None:
        """The multi-line form grep missed when R114 first enumerated by hand."""
        source = (
            "class T:\n"
            "    def test_x(self):\n"
            "        self.assertLessEqual(\n"
            "            source.last_result.elapsed_ms,\n"
            "            120_000,\n"
            "        )\n"
        )
        self.assertEqual(guard.scan_source(source, "probe.py"), {"probe.py::T.test_x": 1})

    def test_it_leaves_lower_bounds_alone(self) -> None:
        """A slow machine only makes a lower bound truer."""
        source = (
            "class T:\n"
            "    def test_x(self):\n"
            "        self.assertGreaterEqual(call['latency_seconds'], 0.0)\n"
            "        self.assertGreater(result.elapsed_ms, 0)\n"
        )
        self.assertEqual(guard.scan_source(source, "probe.py"), {})

    def test_it_names_the_enclosing_test_not_the_module(self) -> None:
        source = (
            "import time\n"
            "class Outer:\n"
            "    def test_a(self):\n"
            "        self.assertLess(time.monotonic(), 1)\n"
            "    def test_b(self):\n"
            "        self.assertLess(time.monotonic(), 1)\n"
        )
        self.assertEqual(
            guard.scan_source(source, "probe.py"),
            {"probe.py::Outer.test_a": 1, "probe.py::Outer.test_b": 1},
        )


class WallClockRegistryTests(unittest.TestCase):
    def test_every_bound_in_the_tree_is_registered(self) -> None:
        observed = guard.scan_tests()
        allowed = guard._load_allowlist()
        self.assertEqual(observed, allowed)

    def test_an_entry_without_a_reason_is_refused(self) -> None:
        payload = {"bounds": {"tests/x.py::T.test_y": {"count": 1, "why": "   "}}}
        with mock.patch.object(guard.Path, "open", mock.mock_open(read_data=json.dumps(payload))):
            with self.assertRaises(SystemExit):
                guard._load_allowlist()

    def test_a_bare_count_is_refused(self) -> None:
        payload = {"bounds": {"tests/x.py::T.test_y": 1}}
        with mock.patch.object(guard.Path, "open", mock.mock_open(read_data=json.dumps(payload))):
            with self.assertRaises(SystemExit):
                guard._load_allowlist()


if __name__ == "__main__":
    unittest.main()
