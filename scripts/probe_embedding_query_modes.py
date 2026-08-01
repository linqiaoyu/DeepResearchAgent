"""Registered, capped Stage-0 embedding probe; it is not a retrieval evaluation."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import certifi
import httpx
from dotenv import dotenv_values

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import DASHSCOPE_EMBEDDING_ENDPOINT, DASHSCOPE_EMBEDDING_MODEL
from deepresearch_agent.rag.evaluation import ChunkSpan, SpanLabel, resolve_labels_to_chunks
from deepresearch_agent.rag.retrieval import ProviderPricing


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "047-stage0-embedding-modes"
PRICE = ProviderPricing(0.5, "aliyun_model_studio_public_20260729")
BUDGET_CNY = 0.05
TRANSLATIONS = {
    "R025": "Compare the Total revenues disclosed in Futu Holdings' 2023 and 2024 fiscal-year 20-F filings, stating each period separately.",
    "R033": "Compare the Total revenue disclosed in Qifu Technology's 2023 and 2024 fiscal-year 20-F filings, stating each period separately.",
    "R036": "Extract the Total revenues table-row values and adjacent period information from iQIYI's fiscal 2024 20-F.",
}


def _tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _embed(
    *, client: httpx.Client, key: str, ledger: LLMClient, text: str, text_type: str | None
) -> tuple[list[float], int, float]:
    # Chinese tokenisation can exceed the character/4 heuristic.  Reserve a
    # conservative per-call ceiling so the shared ledger, rather than a local
    # estimate, remains the active circuit breaker.
    estimate = max(PRICE.cost_cny(_tokens(text)), 0.005)
    ledger.reserve_external_call(run_id=RUN_ID, estimated_cost_cny=estimate)
    payload: dict[str, Any] = {
        "model": DASHSCOPE_EMBEDDING_MODEL,
        "input": text,
        "dimensions": 1024,
    }
    if text_type is not None:
        payload["text_type"] = text_type
    started = time.perf_counter()
    try:
        response = client.post(
            DASHSCOPE_EMBEDDING_ENDPOINT, headers={"Authorization": f"Bearer {key}"}, json=payload
        )
        if response.status_code != 200:
            raise RuntimeError(f"embedding_http_status={response.status_code}")
        body = response.json()
        vector = body["data"][0]["embedding"]
        tokens = int(body.get("usage", {}).get("prompt_tokens", _tokens(text)) or _tokens(text))
        if not isinstance(vector, list) or len(vector) != 1024:
            raise RuntimeError("embedding_response_dimension_mismatch")
    except BaseException:
        ledger.release_external_call(run_id=RUN_ID, estimated_cost_cny=estimate)
        raise
    latency = time.perf_counter() - started
    cost = PRICE.cost_cny(tokens)
    ledger.settle_external_call(
        run_id=RUN_ID,
        role="rag_embedding_probe",
        call_kind="embedding",
        model=DASHSCOPE_EMBEDDING_MODEL,
        input_tokens=tokens,
        cost_cny=cost,
        price_source=PRICE.price_source,
        latency_seconds=latency,
        estimated_cost_cny=estimate,
        metadata={"stage0_probe": True, "text_type": text_type or "omitted"},
    )
    return [float(value) for value in vector], tokens, latency


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    key = str(env.get("DASHSCOPE_API_KEY") or "").strip()
    base = str(env.get("DEEPRESEARCH_QDRANT_URL") or "").rstrip("/")
    collection = str(env.get("DEEPRESEARCH_QDRANT_COLLECTION") or "")
    if not key or not base or not collection:
        raise SystemExit("required provider configuration is absent")
    questions = {
        item["id"]: item
        for item in json.loads((ROOT / "data/golden_set/retrieval_v1/questions.json").read_text())
    }
    database = sqlite3.connect(ROOT / "data/runtime/047-assets.db")
    ledger = LLMClient(
        ledger_path=ROOT / "artifacts/047/stage0_probe_b_ledger.jsonl",
        global_ledger_path=ROOT / "data/runtime/llm_ledger.jsonl",
        budget_cny=BUDGET_CNY,
        completion_func=lambda **_: {},
    )
    ledger.start_run(RUN_ID)
    rows: list[dict[str, object]] = []
    headers = {"api-key": str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or "")}
    with httpx.Client(timeout=30.0, verify=certifi.where()) as client:
        for question_id, english in TRANSLATIONS.items():
            question = questions[question_id]
            labels = [SpanLabel(**label) for label in question["labels"]]
            chunks = [
                ChunkSpan(*row)
                for row in database.execute(
                    "select id, document_version_id, char_start, char_end from chunk where status='ready'"
                )
            ]
            gold = set(resolve_labels_to_chunks(labels, chunks))
            variants = (
                ("chinese_plain", question["question"], None),
                ("english_plain", english, None),
                ("chinese_query", question["question"], "query"),
                ("english_query", english, "query"),
            )
            for name, text, text_type in variants:
                vector, tokens, latency = _embed(
                    client=client, key=key, ledger=ledger, text=text, text_type=text_type
                )
                if ledger.run_total_cny(RUN_ID) > BUDGET_CNY:
                    raise RuntimeError("probe_budget_circuit_breaker")
                response = client.post(
                    f"{base}/collections/{collection}/points/search",
                    headers=headers,
                    json={
                        "vector": vector,
                        "limit": 500,
                        "with_payload": ["chunk_id"],
                        "with_vector": False,
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError(f"search_http_status={response.status_code}")
                hits = response.json()["result"]
                gold_ranks = [
                    index + 1
                    for index, point in enumerate(hits)
                    if point.get("payload", {}).get("chunk_id") in gold
                ]
                rows.append(
                    {
                        "question_id": question_id,
                        "type": question["question_type"],
                        "variant": name,
                        "gold_rank": min(gold_ranks) if gold_ranks else None,
                        "top_score": hits[0]["score"],
                        "gold_score": next(
                            (
                                point["score"]
                                for point in hits
                                if point.get("payload", {}).get("chunk_id") in gold
                            ),
                            None,
                        ),
                        "tokens": tokens,
                        "latency_s": round(latency, 3),
                    }
                )
    output = {
        "run_id": RUN_ID,
        "budget_cny": BUDGET_CNY,
        "cost_cny": ledger.run_total_cny(RUN_ID),
        "rows": rows,
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
