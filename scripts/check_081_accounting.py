"""Acceptance probe for task 081 block C accounting and subprocess timeouts."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from deepresearch_agent.llm import LLMClient, StructuredOutputError
from deepresearch_agent.schemas import ExtractedClaims


def large_payload_worker(_kwargs: dict[str, Any], result_queue: Any) -> None:
    result_queue.put(("ok", {"payload": "x" * 300_000}))


def sleeping_worker(_kwargs: dict[str, Any], _result_queue: Any) -> None:
    time.sleep(2)


def main() -> int:
    calls = 0

    def completion(**_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "choices": [{"message": {"content": "not-json"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = root / ".env"
        env.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
        ledger = root / "ledger.jsonl"
        client = LLMClient(
            ledger_path=ledger, global_ledger_path=root / "global.jsonl",
            budget_cny=3, completion_func=completion, sleep_func=lambda _: None,
            env_path=env,
        )
        try:
            client.complete(
                role="extractor", run_id="081-accounting", schema=ExtractedClaims,
                messages=[{"role": "user", "content": "extract"}],
            )
        except StructuredOutputError:
            pass
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        total = client.run_total_cny("081-accounting")
        print(f"provider_calls={calls} ledger_rows={len(rows)} run_total_cny={total:.8f}")
        payload = LLMClient._call_litellm_in_subprocess(
            kwargs={}, timeout_seconds=3, worker_target=large_payload_worker,
        )
        print(f"returned_bytes={len(payload['payload'].encode())}")
        timed_out = False
        try:
            LLMClient._call_litellm_in_subprocess(
                kwargs={}, timeout_seconds=0.1, worker_target=sleeping_worker,
            )
        except TimeoutError:
            timed_out = True
        print(f"timed_out={timed_out}")
        return int(not (calls == len(rows) == 2 and len(payload["payload"]) >= 256_000 and timed_out))


if __name__ == "__main__":
    raise SystemExit(main())
