"""Ratchet the tests that bound a real clock from above.

R114: ``test_production_subprocess_timeout_terminates_worker`` asserted that a
``spawn`` round trip finished inside a hard-coded 1.0s deadline.  On a loaded
machine interpreter startup alone exceeded that, so the child was terminated
before it ran a single line of the worker body and the test failed reading a
pid file that was never written.  It passed 3/3 in isolation and failed in a
full 1078-test suite: the bound measured machine load, not behaviour.

The class of defect is *any* test assertion that puts an upper bound on a real
clock.  Every such bound races the scheduler, and the constant is invisible
until the day it is too small.  A bound is only meaningful when it is derived
from the thing it discriminates -- how long the blocked operation would have
taken if the deadline under test had never fired -- which is what
``support.timing.assert_deadline_beat_the_operation`` forces the author to name.

So this check finds every upper bound on a clock-derived value under ``tests``
and requires each one to be registered.  The registry is an exact-match ratchet
in both directions: a new bound fails, and so does a stale entry for a bound
that is gone.  Lower bounds are not counted -- a slow machine only makes
``assertGreaterEqual(latency, 0)`` truer.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
ALLOWLIST_PATH = ROOT / "data/timing_assertions/allowlist.json"

#: Reading one of these returns a real, machine-dependent instant.
REAL_CLOCKS = {"monotonic", "perf_counter", "time", "monotonic_ns", "perf_counter_ns"}

#: Names whose value is an elapsed duration even when no clock call is in view,
#: because the measuring happened inside the code under test.
ELAPSED_PREFIXES = ("elapsed", "latency", "duration")

#: Only upper bounds race the scheduler.
UPPER_BOUND_ASSERTIONS = {"assertLess", "assertLessEqual"}


def _is_real_clock_call(node: ast.AST) -> bool:
    """True for ``time.monotonic()`` / ``perf_counter()`` and friends."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in REAL_CLOCKS
    return isinstance(func, ast.Name) and func.id in REAL_CLOCKS


def _looks_like_elapsed(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix) or f"_{prefix}" in lowered for prefix in ELAPSED_PREFIXES)


def _contains_real_clock(node: ast.AST) -> bool:
    return any(_is_real_clock_call(child) for child in ast.walk(node))


def _clock_derived_names(function: ast.AST) -> set[str]:
    """Locals bound to an expression that read a real clock."""
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _contains_real_clock(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _contains_real_clock(node.value) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def _bounds_a_clock(argument: ast.AST, clock_names: set[str]) -> bool:
    if _contains_real_clock(argument):
        return True
    for node in ast.walk(argument):
        if isinstance(node, ast.Name):
            if node.id in clock_names or _looks_like_elapsed(node.id):
                return True
        elif isinstance(node, ast.Attribute) and _looks_like_elapsed(node.attr):
            return True
    return False


def _walk_functions(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """Every function in the module, keyed by its dotted qualname."""
    found: list[tuple[str, ast.AST]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                found.append((qualname, child))
                visit(child, f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def scan_source(source: str, label: str) -> dict[str, int]:
    """Upper bounds on a clock in one module, counted per enclosing function."""
    counts: dict[str, int] = {}
    tree = ast.parse(source, filename=label)
    for qualname, function in _walk_functions(tree):
        clock_names = _clock_derived_names(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in UPPER_BOUND_ASSERTIONS:
                continue
            if _bounds_a_clock(node.args[0], clock_names):
                key = f"{label}::{qualname}"
                counts[key] = counts.get(key, 0) + 1
    return counts


def scan_tests() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        label = path.relative_to(ROOT).as_posix()
        counts.update(scan_source(path.read_text(encoding="utf-8"), label))
    return dict(sorted(counts.items()))


def _load_allowlist() -> dict[str, int]:
    """Registered bounds, each of which must say why it cannot race.

    A bare count would let an entry outlive its reason; requiring ``why`` means
    the next person reading it can tell a deterministic clock from a constant
    somebody guessed.
    """
    with ALLOWLIST_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    entries = payload.get("bounds") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        raise SystemExit(f"invalid allowlist: {ALLOWLIST_PATH}")
    counts: dict[str, int] = {}
    for key, value in entries.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, dict)
            or not isinstance(value.get("count"), int)
            or value["count"] < 0
            or not isinstance(value.get("why"), str)
            or not value["why"].strip()
        ):
            raise SystemExit(
                f"invalid allowlist entry {key!r} in {ALLOWLIST_PATH}: "
                'each entry needs {"count": <int>, "why": "<reason it cannot race>"}'
            )
        counts[key] = value["count"]
    return counts


def _self_test() -> None:
    """Prove the scanner fires on the shape R114 removed."""
    racy = (
        "import time\n"
        "class T:\n"
        "    def test_x(self):\n"
        "        started = time.monotonic()\n"
        "        self.assertLess(time.monotonic() - started, 0.08)\n"
    )
    via_variable = (
        "import time\n"
        "class T:\n"
        "    def test_x(self):\n"
        "        started = time.monotonic()\n"
        "        elapsed = time.monotonic() - started\n"
        "        self.assertLess(elapsed, 10.2)\n"
    )
    reported_elapsed = (
        "class T:\n"
        "    def test_x(self):\n"
        "        self.assertLessEqual(result.elapsed_ms, 120_000)\n"
    )
    lower_bound_is_safe = (
        "import time\n"
        "class T:\n"
        "    def test_x(self):\n"
        "        self.assertGreaterEqual(result.latency_seconds, 0)\n"
    )
    checks = [
        ("inline clock difference", racy, 1),
        ("clock difference via a local", via_variable, 1),
        ("elapsed reported by the code under test", reported_elapsed, 1),
        ("lower bound", lower_bound_is_safe, 0),
    ]
    for label, source, expected in checks:
        found = sum(scan_source(source, "probe.py").values())
        if found != expected:
            raise SystemExit(f"self-test failed: {label} counted {found}, expected {expected}")
    print(f"wall_clock_self_test=PASS cases={len(checks)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()

    observed = scan_tests()
    allowed = _load_allowlist()
    failures: list[str] = []
    for key in sorted(set(observed) | set(allowed)):
        seen = observed.get(key, 0)
        permitted = allowed.get(key)
        if permitted is None:
            failures.append(
                f"unregistered wall-clock bound: {key} observed={seen}. Bound the call by "
                "how long the blocked operation would have taken instead -- see "
                "support.timing.assert_deadline_beat_the_operation -- or register it in "
                f"{ALLOWLIST_PATH.relative_to(ROOT)} with the reason it cannot race."
            )
        elif seen != permitted:
            direction = "lower it to" if seen < permitted else "remove the bound or raise nothing to"
            failures.append(
                f"ratchet mismatch: {key} observed={seen} allowed={permitted}; {direction} {seen}"
            )

    print(
        f"wall_clock_bounds={sum(observed.values())} "
        f"functions={len(observed)} registered={len(allowed)}"
    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
