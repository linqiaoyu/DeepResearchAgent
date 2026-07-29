from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import DASHSCOPE_EMBEDDING_ENDPOINT, DASHSCOPE_RERANK_ENDPOINT
from deepresearch_agent.rag.retrieval import (
    DashScopeEmbeddingProvider,
    DashScopeRerankerProvider,
    FixtureRerankerProvider,
    ProviderPricing,
    RetrievalCandidate,
    _estimated_tokens,
    rrf_fuse,
    rerank_or_degrade,
)
from deepresearch_agent.tools.contracts import ToolErrorKind
from deepresearch_agent.tools.reliable_execution import ToolExecutionError
from scripts.probe_embedding import DEFAULT_EMBEDDING_ENDPOINT
from scripts.probe_rerank import DEFAULT_RERANK_ENDPOINT


class FailingReranker:
    def rerank(self, *_args: object, **_kwargs: object) -> object:
        raise ToolExecutionError(ToolErrorKind.TIMEOUT, "simulated timeout")


class RagRetrievalTests(unittest.TestCase):
    def test_token_estimate_reserves_for_cjk_density(self) -> None:
        self.assertEqual(_estimated_tokens("abcd"), 2)
        self.assertEqual(_estimated_tokens("中文问题"), 8)
        self.assertEqual(_estimated_tokens("中文abcd"), 6)

    def test_probe_defaults_use_public_dashscope_compatible_endpoints(self) -> None:
        self.assertEqual(DEFAULT_EMBEDDING_ENDPOINT, DASHSCOPE_EMBEDDING_ENDPOINT)
        self.assertEqual(DEFAULT_RERANK_ENDPOINT, DASHSCOPE_RERANK_ENDPOINT)
        self.assertEqual(
            DEFAULT_EMBEDDING_ENDPOINT,
            "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        )
        self.assertEqual(
            DEFAULT_RERANK_ENDPOINT,
            "https://dashscope.aliyuncs.com/compatible-api/v1/reranks",
        )

    def test_dashscope_adapters_default_to_public_compatible_endpoints(self) -> None:
        client = LLMClient(
            ledger_path=Path("artifacts/default-endpoint-ledger.jsonl"),
            global_ledger_path=Path("artifacts/default-endpoint-global.jsonl"),
            budget_cny=1.0,
            completion_func=lambda **_: {},
        )
        pricing = ProviderPricing(1.0, "operator-confirmed")
        embedding = DashScopeEmbeddingProvider(
            api_key="test-key",
            ledger=client,
            run_id="rag-run",
            pricing=pricing,
            dimensions=2,
            max_batch_size=2,
        )
        reranker = DashScopeRerankerProvider(
            api_key="test-key", ledger=client, run_id="rag-run", pricing=pricing
        )
        self.assertEqual(embedding.endpoint, DASHSCOPE_EMBEDDING_ENDPOINT)
        self.assertEqual(reranker.endpoint, DASHSCOPE_RERANK_ENDPOINT)

    def test_dashscope_adapters_record_shared_ledger_rows(self) -> None:
        class Response:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self.payload

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.jsonl"
            client = LLMClient(
                ledger_path=ledger,
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                completion_func=lambda **_: {},
            )
            pricing = ProviderPricing(100.0, "operator-confirmed")
            embedding = DashScopeEmbeddingProvider(
                endpoint="https://provider.test/embeddings",
                api_key="test-key",
                ledger=client,
                run_id="rag-run",
                pricing=pricing,
                dimensions=2,
                max_batch_size=2,
            )
            reranker = DashScopeRerankerProvider(
                endpoint="https://provider.test/reranks",
                api_key="test-key",
                ledger=client,
                run_id="rag-run",
                pricing=pricing,
            )
            responses = [
                Response({"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 3}}),
                Response({"results": [{"index": 0, "relevance_score": 0.9}], "usage": {"total_tokens": 4}}),
            ]
            with patch("deepresearch_agent.rag.retrieval.httpx.post", side_effect=responses):
                self.assertEqual(embedding.embed(["这是一个用于稳定预算估算的中文文本"]), [[0.1, 0.2]])
                result = reranker.rerank("问题", [RetrievalCandidate("a", "答案")], 1)

            rows = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(result.candidates[0].chunk_id, "a")
        self.assertEqual(len(rows), 2)
        self.assertIn('"call_kind": "embedding"', rows[0])
        self.assertIn('"call_kind": "rerank"', rows[1])

    def test_rrf_is_deterministic_on_ties(self) -> None:
        candidates = rrf_fuse(
            lexical_ids=["b", "a"], dense_ids=["a", "b"], texts={"a": "alpha", "b": "beta"}, top_k=50
        )
        self.assertEqual([candidate.chunk_id for candidate in candidates], ["a", "b"])

    def test_fail_open_emits_degradation_and_preserves_rrf_order(self) -> None:
        candidates = rrf_fuse(lexical_ids=["a"], dense_ids=[], texts={"a": "alpha"}, top_k=50)
        result, event = rerank_or_degrade(provider=FailingReranker(), query="q", candidates=candidates, top_n=8, fail_open=True)
        self.assertEqual(result, candidates)
        self.assertEqual(event.reason, ToolErrorKind.TIMEOUT)

    def test_fixture_reranker_uses_chunk_id_tie_break(self) -> None:
        candidates = rrf_fuse(lexical_ids=["b", "a"], dense_ids=[], texts={"a": "x", "b": "x"}, top_k=50)
        result, event = rerank_or_degrade(provider=FixtureRerankerProvider(), query="missing", candidates=candidates, top_n=8, fail_open=True)
        self.assertIsNone(event)
        self.assertEqual([candidate.chunk_id for candidate in result], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
