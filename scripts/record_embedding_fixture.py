"""Record one approved DashScope embedding fixture without persisting input text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dotenv import dotenv_values

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.rag.retrieval import DashScopeEmbeddingProvider, ProviderPricing


FIXTURE_INPUT = "DeepResearchAgent embedding recording fixture v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    key = str(dotenv_values(args.env_file).get("DASHSCOPE_API_KEY") or "").strip()
    if not key:
        raise SystemExit("DASHSCOPE_API_KEY is required")
    ledger = LLMClient(
        ledger_path=args.ledger,
        global_ledger_path=Path("data/runtime/llm_ledger.jsonl"),
        budget_cny=1.0,
        completion_func=lambda **_: {},
    )
    run_id = "047-embedding-recording-v1"
    ledger.start_run(run_id)
    vector = DashScopeEmbeddingProvider(
        api_key=key,
        ledger=ledger,
        run_id=run_id,
        pricing=ProviderPricing(0.5, "aliyun_model_studio_public_20260729"),
        dimensions=1024,
        max_batch_size=1,
    ).embed([FIXTURE_INPUT])[0]
    payload = {
        "schema_version": 1,
        "model": "text-embedding-v4",
        "dimensions": len(vector),
        "records": [{
            "input_sha256": hashlib.sha256(FIXTURE_INPUT.encode("utf-8")).hexdigest(),
            "embedding": vector,
        }],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": payload["model"], "dimensions": len(vector), "records": 1}))


if __name__ == "__main__":
    main()
