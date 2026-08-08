"""Prove the provider worker is reused, killable, and not charged for startup.

Three properties, each independently falsifiable:

``worker reuse``
    N provider calls must cost one worker spawn and one SDK import. Spawning
    per call is what made R090's live validation impossible: importing litellm
    (1812 modules) took about 15 minutes on the run host, so no call could
    finish inside any role's timeout.

``killability``
    An overdue call must still terminate its worker process, and the next call
    must get a fresh one -- otherwise a late response could be handed to the
    wrong request.

``startup is not call latency``
    A worker that is slow to become ready must not consume the call timeout.
    Importing the SDK is local work, not a provider transport.

The stub worker loop here never imports litellm; it counts what a real one
would do, so the check runs offline with no key and no spend.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepresearch_agent.llm.client import _ProviderWorkerPool  # noqa: E402

READY_MARKER = "READY"


def counting_worker_loop(request_queue, response_queue, ready_queue) -> None:  # type: ignore[no-untyped-def]
    """Serve calls after one simulated SDK import, reporting the serving pid.

    The SDK import happens once per worker process, so the number of distinct
    pids that served the calls *is* the number of imports. Reporting a constant
    here instead would make the import count unfalsifiable.
    """

    import os as _os

    ready_queue.put(("ok", None))
    while True:
        request = request_queue.get()
        if request is None:
            return
        if request.get("hang"):
            time.sleep(30)
            continue
        response_queue.put(("ok", {"echo": request.get("n"), "pid": _os.getpid()}))


def slow_start_worker_loop(request_queue, response_queue, ready_queue) -> None:  # type: ignore[no-untyped-def]
    """Become ready only after a delay longer than the call timeout."""

    time.sleep(2.0)
    ready_queue.put(("ok", None))
    while True:
        request = request_queue.get()
        if request is None:
            return
        response_queue.put(("ok", {"echo": request.get("n"), "imports": 1}))


def _reuse() -> tuple[int, int, int]:
    pool = _ProviderWorkerPool(worker_loop=counting_worker_loop)
    try:
        serving_pids = set()
        calls = 0
        for index in range(5):
            payload = pool.call({"n": index}, timeout_seconds=10)
            serving_pids.add(payload["pid"])
            calls += 1
        return pool.spawns, calls, len(serving_pids)
    finally:
        pool.close()


def _killability() -> tuple[bool, bool]:
    pool = _ProviderWorkerPool(worker_loop=counting_worker_loop)
    try:
        first = pool.call({"n": 0}, timeout_seconds=10)
        assert first["echo"] == 0
        hung_pid = None
        for worker in list(pool._workers.values()):
            hung_pid = worker.process.pid
        try:
            pool.call({"hang": True}, timeout_seconds=1.0)
            timed_out = False
        except TimeoutError:
            timed_out = True
        time.sleep(0.5)
        killed = timed_out and not _pid_alive(hung_pid)
        spawns_before = pool.spawns
        payload = pool.call({"n": 1}, timeout_seconds=10)
        fresh = payload["echo"] == 1 and pool.spawns == spawns_before + 1
        return killed, fresh
    finally:
        pool.close()


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    import os

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _startup_not_charged() -> bool:
    """A 2s startup must not fail a 0.5s call."""

    pool = _ProviderWorkerPool(
        worker_loop=slow_start_worker_loop,
        startup_timeout_seconds=30,
    )
    try:
        payload = pool.call({"n": 7}, timeout_seconds=0.5)
        return bool(payload["echo"] == 7)
    except TimeoutError:
        return False
    finally:
        pool.close()


def _parent_stays_sdk_free() -> bool:
    """Constructing a production client must not import the SDK here.

    The parent used to import litellm only to bind a `.completion` that
    production never calls, paying a second full import per process.
    """

    import tempfile

    from deepresearch_agent.llm.client import LLMClient

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("DEEPSEEK_API_KEY=placeholder\n", encoding="utf-8")
        LLMClient(
            ledger_path=root / "ledger.jsonl",
            global_ledger_path=root / "global.jsonl",
            budget_cny=1.0,
            env_path=root / ".env",
        )
    return "litellm" not in sys.modules


def self_test() -> int:
    parent_clean = _parent_stays_sdk_free()
    spawns, calls, imports = _reuse()
    killed, fresh = _killability()
    startup_ok = _startup_not_charged()
    print(f"parent_process_imports_sdk={str(not parent_clean).lower()}")
    print(f"worker_spawns={spawns} provider_calls={calls} litellm_imports={imports}")
    print(
        f"timeout_kills_worker={str(killed).lower()} "
        f"next_call_gets_fresh_worker={str(fresh).lower()}"
    )
    print(f"slow_startup_does_not_consume_call_timeout={str(startup_ok).lower()}")
    failures: list[str] = []
    if not parent_clean:
        failures.append("constructing a production client imported the SDK in this process")
    if spawns != 1:
        failures.append(f"{calls} calls cost {spawns} worker spawns, expected 1")
    if imports != 1:
        failures.append(f"{imports} SDK imports across {calls} calls, expected 1")
    if not killed:
        failures.append("an overdue call did not terminate its worker process")
    if not fresh:
        failures.append("the call after a timeout did not get a fresh worker")
    if not startup_ok:
        failures.append("worker startup was charged to the call timeout")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    print(f"provider_worker_failures={len(failures)}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test:
        parser.error("--self-test is required")
    return self_test()


if __name__ == "__main__":
    raise SystemExit(main())
