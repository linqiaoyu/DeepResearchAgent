"""Timing assertions that survive a loaded machine.

R114: a deadline test asserted that a ``spawn`` round trip finished inside a
hard-coded 1.0s.  Interpreter startup alone can exceed that under load, so the
child was terminated before it ran a line of its body and the test failed on a
pid file that was never written -- passing 3/3 alone and failing in the full
suite.  The constant was measuring machine load, not the behaviour under test.

Every deadline test here discriminates the same two outcomes:

* the deadline fired and the call returned early, or
* the deadline did not fire and the call waited for the blocked operation.

So the only bound that means anything is *how long the blocked operation would
have taken*.  That number is a property of the test, identical on every machine,
and it keeps the test falsifiable: break the deadline and the call waits the
operation out, blowing the bound.  Passing it explicitly is what
``assert_deadline_beat_the_operation`` is for -- a bare constant cannot say
which of the two outcomes it separates.

``scripts/check_wall_clock_assertions.py`` ratchets the alternatives away.
"""

from __future__ import annotations

import multiprocessing
import time
import unittest
from typing import Any


#: Long enough that no deadline under test can be confused with it, short enough
#: that a genuinely broken deadline fails the suite instead of hanging it.
BLOCKED_FOR_SECONDS = 5.0

_spawn_cost_seconds: float | None = None


def _immediately_return(_kwargs: dict[str, Any], result_queue: Any) -> None:
    """Worker body that does nothing but prove the interpreter came up."""
    result_queue.put(("ok", {}))


def process_spawn_cost_seconds() -> float:
    """What one spawn-and-answer round trip costs on this machine.

    Measured once per process against the same ``spawn`` context production
    uses, so a deadline can be set relative to interpreter startup instead of
    racing it.  A fixed constant cannot do that: the cost differs by an order of
    magnitude between an idle laptop and a loaded CI runner.
    """
    global _spawn_cost_seconds
    if _spawn_cost_seconds is None:
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_immediately_return,
            args=({}, result_queue),
            daemon=True,
        )
        started = time.perf_counter()
        try:
            process.start()
            result_queue.get(timeout=120)
            _spawn_cost_seconds = time.perf_counter() - started
        finally:
            process.join(timeout=30)
            if process.is_alive():  # pragma: no cover - only on a wedged runner
                process.terminate()
                process.join(timeout=30)
            result_queue.close()
            result_queue.join_thread()
    return _spawn_cost_seconds


def assert_deadline_beat_the_operation(
    case: unittest.TestCase,
    *,
    elapsed_seconds: float,
    blocked_for_seconds: float,
    what: str,
    overhead_seconds: float = 0.0,
) -> None:
    """Assert a call returned via its deadline, not by waiting the operation out.

    ``blocked_for_seconds`` is how long the operation under the deadline blocks
    for.  ``overhead_seconds`` covers cost the test cannot avoid paying -- process
    spawns, say -- and must itself be measured rather than guessed.
    """
    budget = blocked_for_seconds + overhead_seconds
    case.assertLess(
        elapsed_seconds,
        budget,
        f"{what}: returned after {elapsed_seconds:.3f}s with a budget of "
        f"{budget:.3f}s (operation blocks for {blocked_for_seconds:.3f}s, "
        f"measured overhead {overhead_seconds:.3f}s). The deadline did not fire -- "
        "the call waited for the blocked operation instead.",
    )
