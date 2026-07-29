from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, replace
from typing import Protocol

import httpx

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import (
    DASHSCOPE_EMBEDDING_ENDPOINT,
    DASHSCOPE_EMBEDDING_MODEL,
    DASHSCOPE_RERANK_ENDPOINT,
    DASHSCOPE_RERANK_MODEL,
)
from deepresearch_agent.tools.contracts import DegradationEvent
from deepresearch_agent.tools.reliable_execution import ToolExecutionError, classify_tool_error


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: str
    text: str
    lexical_rank: int | None = None
    dense_rank: int | None = None
    lexical_score: float | None = None
    dense_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


@dataclass(frozen=True)
class RerankResult:
    candidates: list[RetrievalCandidate]
    candidate_count: int
    token_usage: int = 0
    latency_ms: int = 0


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class RerankerProvider(Protocol):
    def rerank(self, query: str, candidates: list[RetrievalCandidate], top_n: int) -> RerankResult: ...


@dataclass(frozen=True)
class ProviderPricing:
    cny_per_million_input_tokens: float
    price_source: str

    def cost_cny(self, input_tokens: int) -> float:
        return input_tokens * self.cny_per_million_input_tokens / 1_000_000


class DashScopeEmbeddingProvider:
    """Direct embedding adapter with pre-reserved shared-ledger accounting."""

    fidelity = "real"

    def __init__(
        self,
        *,
        endpoint: str = DASHSCOPE_EMBEDDING_ENDPOINT,
        api_key: str,
        ledger: LLMClient,
        run_id: str,
        pricing: ProviderPricing,
        dimensions: int,
        max_batch_size: int,
    ) -> None:
        if not endpoint or not api_key or max_batch_size < 1 or dimensions < 1:
            raise ValueError("DashScope embedding endpoint, key, dimensions and batch size are required")
        self.endpoint = endpoint
        self.api_key = api_key
        self.ledger = ledger
        self.run_id = run_id
        self.pricing = pricing
        self.dimensions = dimensions
        self.max_batch_size = max_batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.max_batch_size):
            batch = texts[offset : offset + self.max_batch_size]
            estimated_tokens = sum(_estimated_tokens(value) for value in batch)
            estimate = self.pricing.cost_cny(estimated_tokens)
            self.ledger.reserve_external_call(run_id=self.run_id, estimated_cost_cny=estimate)
            started = time.perf_counter()
            try:
                response = httpx.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": DASHSCOPE_EMBEDDING_MODEL, "input": batch, "dimensions": self.dimensions},
                    timeout=60.0,
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data", [])
                if len(data) != len(batch):
                    raise ValueError("embedding response count does not match request")
                returned = [item["embedding"] for item in data]
                if any(len(vector) != self.dimensions for vector in returned):
                    raise ValueError("embedding response dimension does not match configured dimension")
                tokens = int(payload.get("usage", {}).get("prompt_tokens", estimated_tokens) or estimated_tokens)
            except BaseException as exc:
                self.ledger.release_external_call(run_id=self.run_id, estimated_cost_cny=estimate)
                raise ToolExecutionError(classify_tool_error(exc), str(exc)) from exc
            self.ledger.settle_external_call(
                run_id=self.run_id,
                role="rag_embedding",
                call_kind="embedding",
                model=DASHSCOPE_EMBEDDING_MODEL,
                input_tokens=tokens,
                cost_cny=self.pricing.cost_cny(tokens),
                price_source=self.pricing.price_source,
                latency_seconds=time.perf_counter() - started,
                estimated_cost_cny=estimate,
                metadata={"dimensions": self.dimensions, "input_count": len(batch)},
            )
            vectors.extend(returned)
        return vectors


class DashScopeRerankerProvider:
    fidelity = "real"

    def __init__(
        self,
        *,
        endpoint: str = DASHSCOPE_RERANK_ENDPOINT,
        api_key: str,
        ledger: LLMClient,
        run_id: str,
        pricing: ProviderPricing,
    ) -> None:
        if not endpoint or not api_key:
            raise ValueError("DashScope rerank endpoint and key are required")
        self.endpoint = endpoint
        self.api_key = api_key
        self.ledger = ledger
        self.run_id = run_id
        self.pricing = pricing

    def rerank(self, query: str, candidates: list[RetrievalCandidate], top_n: int) -> RerankResult:
        estimated_tokens = _estimated_tokens(query) * len(candidates) + sum(
            _estimated_tokens(candidate.text) for candidate in candidates
        )
        estimate = self.pricing.cost_cny(estimated_tokens)
        self.ledger.reserve_external_call(run_id=self.run_id, estimated_cost_cny=estimate)
        started = time.perf_counter()
        try:
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": DASHSCOPE_RERANK_MODEL,
                    "query": query,
                    "documents": [candidate.text for candidate in candidates],
                    "top_n": top_n,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results")
            if not isinstance(results, list):
                raise ValueError("rerank response does not contain results")
            ranked = [
                replace(candidates[int(item["index"])], rerank_score=float(item["relevance_score"]))
                for item in results
            ]
            tokens = int(payload.get("usage", {}).get("total_tokens", estimated_tokens) or estimated_tokens)
        except BaseException as exc:
            self.ledger.release_external_call(run_id=self.run_id, estimated_cost_cny=estimate)
            raise ToolExecutionError(classify_tool_error(exc), str(exc)) from exc
        latency = time.perf_counter() - started
        self.ledger.settle_external_call(
            run_id=self.run_id,
            role="rag_rerank",
            call_kind="rerank",
            model=DASHSCOPE_RERANK_MODEL,
            input_tokens=tokens,
            cost_cny=self.pricing.cost_cny(tokens),
            price_source=self.pricing.price_source,
            latency_seconds=latency,
            estimated_cost_cny=estimate,
            metadata={"candidate_count": len(candidates)},
        )
        ranked.sort(key=lambda candidate: (-(candidate.rerank_score or 0.0), candidate.chunk_id))
        return RerankResult(ranked[:top_n], len(candidates), tokens, round(latency * 1000))


class EmptyRagSearchTool:
    """Safe pre-index implementation: never fabricates retrieval candidates."""

    fidelity = "fixture"

    def search(self, *, query: str, as_of: str) -> dict[str, object]:
        return {"candidates": [], "trace": {"query": query, "as_of": as_of, "status": "empty_index"}}


class FixtureEmbeddingProvider:
    fidelity = "fixture"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embedding(text) for text in texts]


class FixtureRerankerProvider:
    fidelity = "fixture"

    def rerank(self, query: str, candidates: list[RetrievalCandidate], top_n: int) -> RerankResult:
        query_terms = set(query.lower().split())
        ranked = [
            replace(
                candidate,
                rerank_score=float(len(query_terms & set(candidate.text.lower().split()))),
            )
            for candidate in candidates
        ]
        ranked.sort(key=lambda candidate: (-(candidate.rerank_score or 0.0), candidate.chunk_id))
        return RerankResult(candidates=ranked[:top_n], candidate_count=len(candidates))


def rrf_fuse(
    *,
    lexical_ids: list[str],
    dense_ids: list[str],
    texts: dict[str, str],
    top_k: int,
    lexical_scores: dict[str, float] | None = None,
    dense_scores: dict[str, float] | None = None,
) -> list[RetrievalCandidate]:
    """Fuse ranked lists while retaining each backend's native score.

    RRF intentionally ranks on positions, but callers still need the native
    lexical and dense scores to explain a returned candidate.  Missing scores
    remain explicit ``None`` rather than being invented from rank.
    """

    lexical_scores = lexical_scores or {}
    dense_scores = dense_scores or {}
    scores: dict[str, float] = {}
    positions: dict[str, dict[str, int]] = {}
    for kind, identifiers in (("lexical", lexical_ids), ("dense", dense_ids)):
        for rank, identifier in enumerate(identifiers, 1):
            scores[identifier] = scores.get(identifier, 0.0) + 1 / (60 + rank)
            positions.setdefault(identifier, {})[kind] = rank
    candidates = [
        RetrievalCandidate(
            chunk_id=identifier,
            text=texts[identifier],
            lexical_rank=positions[identifier].get("lexical"),
            dense_rank=positions[identifier].get("dense"),
            lexical_score=lexical_scores.get(identifier),
            dense_score=dense_scores.get(identifier),
            rrf_score=score,
        )
        for identifier, score in scores.items()
    ]
    return sorted(candidates, key=lambda candidate: (-candidate.rrf_score, candidate.chunk_id))[:top_k]


def rerank_or_degrade(*, provider: RerankerProvider, query: str, candidates: list[RetrievalCandidate], top_n: int, fail_open: bool) -> tuple[list[RetrievalCandidate], DegradationEvent | None]:
    try:
        result = provider.rerank(query, candidates, top_n)
    except ToolExecutionError as exc:
        if not fail_open:
            raise
        return candidates[:top_n], DegradationEvent(tool="rerank", reason=exc.kind, impact="rrf_top_n_used", attempts=1)
    return result.candidates, None


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0


def _embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [byte / 255 for byte in digest[:8]]


def _estimated_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))
