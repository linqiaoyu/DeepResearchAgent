# 114 result

Merging R112 and R113 into `main` took two full gate runs. The first was red:

```
ERROR: test_production_subprocess_timeout_terminates_worker
  (unit.test_llm_integration.LLMIntegrationTests.test_production_subprocess_timeout_terminates_worker)
  File "tests/unit/test_llm_integration.py", line 90, in test_production_subprocess_timeout_terminates_worker
    child_pid = int(pid_path.read_text(encoding="utf-8"))
FileNotFoundError: [Errno 2] No such file or directory: '.../child.pid'

Ran 1078 tests in 72.045s
FAILED (errors=1, skipped=7)
```

The second was green. Nothing about the product changed between them.

## What the constant was actually measuring

The test spawns a worker that writes its pid and then sleeps, and gives the
parent a 1.0s deadline to kill it. `multiprocessing` uses the `spawn` context
here, so the child boots a fresh interpreter before it runs a line of the worker
body. Under a loaded 1078-test suite that boot exceeded 1.0s, `terminate()`
landed while the child was still starting, and the pid file was never written.

The test passed 3/3 in isolation at 1.02s each and failed inside the full suite.
It was measuring how busy the machine was.

Both the test and `src/deepresearch_agent/llm/client.py` were byte-identical to
`main`, so R112/R113 could not have caused it. It was pre-existing, and merging
went ahead on that basis.

## Why widening the constant is not the fix

Every deadline test in this repository discriminates the same two outcomes:

* the deadline fired and the call returned early, or
* the deadline never fired and the call waited for the blocked operation.

A constant separates those two only by accident, and only until the machine
changes. The quantity that actually separates them is **how long the blocked
operation blocks for** -- a property of the test, identical everywhere. Raising
1.0s to 3.0s would have moved the threshold, not removed it, and the next round
would have found it again on a slower runner.

`support.timing.assert_deadline_beat_the_operation` makes the caller name that
duration. For the subprocess test both numbers are now derived from measured
spawn cost, so the 10x gap between deadline and block holds on a fast laptop and
a loaded CI runner alike.

## The class, not the instance

AGENTS.md section 8 requires enumerating the whole class. The class is every
upper bound on a clock-derived value under `tests/` -- lower bounds are safe,
because a slow machine only makes `assertGreaterEqual(latency, 0)` truer.

A grep sweep found 7. An AST scan found **8**: the extra one was

```python
self.assertLessEqual(
    source.last_result.elapsed_ms,
    120_000,
)
```

split across lines so no single line carried both the assertion and the value.
That is the argument for the scanner over a careful reading: the enumeration
that fixes this class cannot itself be line-based. The scanner was written
first and used to produce the list.

| member | was | now |
|---|---|---|
| `test_production_subprocess_timeout_terminates_worker` | `< 2.5`, deadline `1.0` | helper; both derived from measured spawn cost |
| `test_main_thread_hard_timeout_interrupts_event_wait` | `< 0.5` | helper, bound by the block |
| `test_akshare_timeout_terminates_every_blocked_worker` | `< 10.2` for 20 spawns | helper; overhead measured, not guessed |
| `test_timeout_is_enforced_and_counts_as_a_breaker_failure` | `< 0.15` | helper, bound by the block |
| `test_blocked_worker_returns_by_deadline_without_overlapping_retry` | `< 0.08` | helper, bound by the block |
| `test_blocked_cninfo_worker_is_quarantined_across_runs` | `< 0.1` | helper, bound by the block |
| `test_timeout_retries_inside_total_deadline_then_degrades` | `<= 120_000` | reads `DISCLOSURE_TOOL_SPEC.total_timeout_s` |
| `test_total_deadline_bounds_the_complete_retry_envelope` | `<= 1_000` | unchanged; registered as FakeClock-driven |

`10.2` deserves its own note. Twenty process spawns against roughly 0.5s of
headroom each is the same order as spawning an interpreter, so that test was
sitting on the same fault as the one that fired -- it simply had not been
unlucky yet.

Two unbounded `release.wait()` calls were also given a bound. Unbounded, a
deadline that stops firing **hangs** the suite, and the elapsed assertion guarding
it never runs at all. Bounded, that regression fails instead.

## Enforcement

`scripts/check_wall_clock_assertions.py` runs in `scripts/gate.py`, and CI
invokes the gate, so it runs there too.

```
wall_clock_self_test=PASS cases=4
wall_clock_bounds=3 functions=3 registered=3
```

Three bounds remain, each registered with the reason it cannot race: the helper
itself (the sanctioned chokepoint), the FakeClock-driven one, and the one that
reads its ceiling off `DISCLOSURE_TOOL_SPEC`. The ratchet fails in both
directions, and an entry without a stated reason is refused -- a bare count
would let a registration outlive the reason it was granted.

## Counterexamples

Each is a real run, saved with its raw output.

1. Restoring a raw bound (`self.assertLess(time.monotonic() - started, 0.08)`):
   `unregistered wall-clock bound: ... observed=1`, exit 1.
2. Raising a registered count from 1 to 2:
   `ratchet mismatch: ... observed=1 allowed=2; lower it to 1`, exit 1.
3. Putting the deadline back below spawn cost reproduces the original failure
   exactly -- same `FileNotFoundError`, same line.
4. Feeding the helper an elapsed that waited the operation out:
   `5.2 not less than 5.0 : tool timeout enforcement: ... The deadline did not
   fire -- the call waited for the blocked operation instead.`

Counterexample 4 needs a hang-then-report implementation, which no constant in
the suite can produce, so it is fed to the helper directly rather than staged as
an in-suite mutation.

## Result

```
Ran 1086 tests in 58.731s
OK (skipped=7)
GATE_EXIT=0
```

Three further consecutive full-suite runs: `OK (skipped=7)` at 57.086s, 56.824s,
56.579s. Four green runs is evidence the flake is gone, not proof -- the failure
was stochastic and load-dependent, and the honest claim is that the mechanism
that caused it has been removed, not that absence has been demonstrated.

## Not established

* No CI-side measurement. Every number here is from one macOS laptop; the GitHub
  runner's spawn cost is unmeasured. The fix is designed to be insensitive to
  that, which is exactly the claim a single machine cannot check.
* The scanner keys on `assertLess`/`assertLessEqual` and on names that look like
  elapsed values. A bound written as `assertTrue(elapsed < 0.1)`, or through a
  clock-derived value with an unrelated name, would not be counted.
* `process_spawn_cost_seconds()` measures a `spawn` round trip and is also used
  as the overhead estimate for the AKShare test, which forks. Fork is cheaper, so
  the budget is generous in the safe direction, but it is not a measurement of
  what that test actually pays.
