"""Prove bounded hybrid retrieval, configuration refusal, and accounting."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
from unittest.mock import patch

from deepresearch_agent.config_validation import ConfigurationError
from deepresearch_agent.llm import LLMClient
from deepresearch_agent.rag.backends import QdrantDenseBackend, StorageLexicalBackend
from deepresearch_agent.rag.factory import build_rag_search
from deepresearch_agent.rag.retrieval import (
    DashScopeEmbeddingProvider,
    DashScopeRerankerProvider,
    ProviderPricing,
    RerankResult,
    RetrievalCandidate,
)
from deepresearch_agent.rag.search import RagSearchService, RetrievalFilter, SearchChunk
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import ToolErrorKind, ToolExecutionError
from deepresearch_agent.trajectory import TrajectoryRecorder, trajectory_recording

from check_rag_ingestion import measure as measure_ingestion


class _RecordedBackend:
    fidelity = "replay"

    def __init__(self, chunk: SearchChunk) -> None:
        self.chunk = chunk
        self.calls = 0

    def search(
        self, *, query: str, filters: RetrievalFilter, limit: int
    ) -> list[SearchChunk]:
        del query, filters
        self.calls += 1
        return [self.chunk][:limit]


class _RecordedReranker:
    fidelity = "replay"

    def rerank(
        self, query: str, candidates: list[RetrievalCandidate], top_n: int
    ) -> RerankResult:
        del query
        return RerankResult(candidates[:top_n], len(candidates))


class _FailingReranker:
    fidelity = "replay"

    def rerank(self, *_args: object, **_kwargs: object) -> RerankResult:
        raise ToolExecutionError(ToolErrorKind.TIMEOUT, "recorded timeout")


def _service(*, fail_open: bool, reranker: object) -> tuple[RagSearchService, _RecordedBackend, _RecordedBackend]:
    chunk = SearchChunk(
        "chunk-1",
        "revenue increased",
        date(2025, 12, 31),
        "document-version-1",
        0,
        17,
        source_url="https://example.test/filing",
        published_at=date(2026, 3, 1),
    )
    lexical = _RecordedBackend(chunk)
    dense = _RecordedBackend(chunk)
    return (
        RagSearchService(
            lexical=lexical,
            dense=dense,
            reranker=reranker,  # type: ignore[arg-type]
            retrieval_top_k=5,
            rerank_top_n=3,
            rerank_enabled=True,
            rerank_fail_open=fail_open,
            index_version="idx-v1",
        ),
        lexical,
        dense,
    )


def _provider_accounting(root: Path) -> tuple[int, int, int]:
    ledger_path = root / "rag-ledger.jsonl"
    global_path = root / "global-ledger.jsonl"
    ledger = LLMClient(
        ledger_path=ledger_path,
        global_ledger_path=global_path,
        budget_cny=1.0,
        completion_func=lambda **_: {},
    )
    run_id = "rag-recorded-boundaries"
    ledger.start_run(run_id)
    pricing = ProviderPricing(0.5, "recorded-contract-price")
    embedding = DashScopeEmbeddingProvider(
        api_key="not-a-live-key",
        ledger=ledger,
        run_id=run_id,
        pricing=pricing,
        dimensions=2,
        max_batch_size=10,
    )
    reranker = DashScopeRerankerProvider(
        api_key="not-a-live-key",
        ledger=ledger,
        run_id=run_id,
        pricing=pricing,
    )
    recorder = TrajectoryRecorder(run_id=run_id, request={})
    responses = [
        {"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 2}},
        {
            "results": [{"index": 0, "relevance_score": 0.9}],
            "usage": {"total_tokens": 3},
        },
    ]
    with patch("deepresearch_agent.rag.retrieval._post_json", side_effect=responses), trajectory_recording(recorder):
        embedding.embed(["query"])
        reranker.rerank(
            "query",
            [RetrievalCandidate(chunk_id="chunk-1", text="revenue increased")],
            1,
        )
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    retrieval_calls = [
        *recorder.trajectory.embedding_calls,
        *recorder.trajectory.rerank_calls,
    ]
    return 2, len(rows), len(retrieval_calls)


def measure() -> dict[str, int | float]:
    implementations = (
        StorageLexicalBackend,
        QdrantDenseBackend,
        DashScopeRerankerProvider,
    )
    available = sum(getattr(item, "fidelity", None) == "real" for item in implementations)
    missing_rejected = 0
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        try:
            build_rag_search(
                Settings(storage_path=root / "missing.db", rag_enabled=True),
                environ={},
            )
        except ConfigurationError:
            missing_rejected = 1

        provider_calls, ledger_rows, retrieval_traces = _provider_accounting(root)

    service, lexical, dense = _service(fail_open=True, reranker=_RecordedReranker())
    recorder = TrajectoryRecorder(run_id="hybrid", request={})
    with trajectory_recording(recorder):
        result = service.search(query="revenue", as_of="2026-08-11")

    open_service, _, _ = _service(fail_open=True, reranker=_FailingReranker())
    open_result = open_service.search(query="revenue", as_of="2026-08-11")
    closed_service, _, _ = _service(fail_open=False, reranker=_FailingReranker())
    closed_result = closed_service.search(query="revenue", as_of="2026-08-11")
    ingestion = measure_ingestion()
    return {
        "retrieval_layers_available": available,
        "retrieval_layers_exercised": int(lexical.calls > 0)
        + int(dense.calls > 0)
        + int(result["trace"].rerank_status == "ok"),
        "missing_config_silent_startups": 1 - missing_rejected,
        "rerank_fail_open_candidates": len(open_result["candidates"]),
        "rerank_fail_closed_candidates": len(closed_result["candidates"]),
        "search_trajectory_coverage": len(recorder.trajectory.tool_calls),
        "provider_cost_coverage": ledger_rows / provider_calls,
        "provider_trajectory_coverage": retrieval_traces / provider_calls,
        "indexed_chunk_provenance_rate": ingestion["indexed_chunk_provenance_rate"],
        "undated_visible_documents": ingestion["undated_visible_documents"],
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "retrieval_layers_available": 3,
        "retrieval_layers_exercised": 3,
        "missing_config_silent_startups": 0,
        "rerank_fail_open_candidates": 1,
        "rerank_fail_closed_candidates": 0,
        "search_trajectory_coverage": 1,
        "provider_cost_coverage": 1.0,
        "provider_trajectory_coverage": 1.0,
        "indexed_chunk_provenance_rate": 1.0,
        "undated_visible_documents": 0,
    }
    return [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("rag_retrieval_self_test=FAIL production probe is dirty")
    mutations = {
        "missing_layer": {**metrics, "retrieval_layers_exercised": 2},
        "silent_config": {**metrics, "missing_config_silent_startups": 1},
        "fail_open_lost": {**metrics, "rerank_fail_open_candidates": 0},
        "fail_closed_leak": {**metrics, "rerank_fail_closed_candidates": 1},
        "missing_cost": {**metrics, "provider_cost_coverage": 0.5},
        "missing_trace": {**metrics, "provider_trajectory_coverage": 0.5},
    }
    for label, broken in mutations.items():
        if not evaluate(broken):
            raise SystemExit(f"rag_retrieval_self_test=FAIL accepted {label}")
    print(f"rag_retrieval_self_test=PASS cases={len(mutations) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
