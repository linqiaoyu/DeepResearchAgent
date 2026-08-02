from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import httpx

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import (
    DASHSCOPE_EMBEDDING_ENDPOINT,
    DASHSCOPE_EMBEDDING_MODEL,
    DASHSCOPE_RERANK_ENDPOINT,
    DASHSCOPE_RERANK_MODEL,
)
from deepresearch_agent.tools.contracts import DegradationEvent, ToolSpec
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RunToolContext,
    ToolExecutionError,
    classify_tool_error,
)
from deepresearch_agent.trajectory import RetrievalCallTrace, active_trajectory_recorder


RAG_EMBEDDING_TOOL_SPEC = ToolSpec(
    name="rag_embedding",
    version="1",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    timeout_s=60.0,
    total_timeout_s=180.0,
    cost_class="low",
    idempotent=True,
    has_side_effect=False,
)
RAG_RERANK_TOOL_SPEC = ToolSpec(
    name="rag_rerank",
    version="1",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    timeout_s=60.0,
    total_timeout_s=180.0,
    cost_class="low",
    idempotent=True,
    has_side_effect=False,
)


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


class RecordedEmbeddingProvider:
    """Offline embedding fixture keyed only by content SHA-256."""

    fidelity = "replay"

    def __init__(self, recording: Path) -> None:
        payload = json.loads(recording.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("embedding recording schema_version must be 1")
        dimensions = payload.get("dimensions")
        records = payload.get("records")
        if not isinstance(dimensions, int) or dimensions < 1 or not isinstance(records, list):
            raise ValueError("embedding recording metadata is invalid")
        vectors: dict[str, list[float]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("embedding recording item is invalid")
            digest = record.get("input_sha256")
            vector = record.get("embedding")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(vector, list)
                or len(vector) != dimensions
                or not all(isinstance(value, (int, float)) for value in vector)
            ):
                raise ValueError("embedding recording item is invalid")
            vectors[digest] = [float(value) for value in vector]
        if len(vectors) != len(records):
            raise ValueError("embedding recording contains duplicate input hashes")
        self.model = payload.get("model")
        self.dimensions = dimensions
        self._vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            vector = self._vectors.get(digest)
            if vector is None:
                raise ValueError("embedding recording cache_miss")
            result.append(list(vector))
        return result


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
        executor: ReliableToolExecutor | None = None,
        tool_context: RunToolContext | None = None,
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
        self.executor = executor or ReliableToolExecutor()
        self.tool_context = tool_context or RunToolContext.for_run()

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
                result = self.executor.execute(
                    RAG_EMBEDDING_TOOL_SPEC,
                    lambda: _post_json(
                        self.endpoint,
                        {"Authorization": f"Bearer {self.api_key}"},
                        {"model": DASHSCOPE_EMBEDDING_MODEL, "input": batch, "dimensions": self.dimensions},
                    ),
                    self.tool_context,
                )
                if not result.ok:
                    assert result.error is not None
                    raise ToolExecutionError(result.error.kind, result.error.message)
                payload = result.value
                assert isinstance(payload, dict)
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
                metadata={
                    "dimensions": self.dimensions,
                    "input_count": len(batch),
                    "tool_error_summary": [event.model_dump(mode="json") for event in self.tool_context.degradation_events],
                },
            )
            _record_retrieval_call(
                call_kind="embedding",
                model=DASHSCOPE_EMBEDDING_MODEL,
                inputs=batch,
                dimensions=self.dimensions,
                token_count=tokens,
                cost_cny=self.pricing.cost_cny(tokens),
                latency_seconds=time.perf_counter() - started,
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
        executor: ReliableToolExecutor | None = None,
        tool_context: RunToolContext | None = None,
    ) -> None:
        if not endpoint or not api_key:
            raise ValueError("DashScope rerank endpoint and key are required")
        self.endpoint = endpoint
        self.api_key = api_key
        self.ledger = ledger
        self.run_id = run_id
        self.pricing = pricing
        self.executor = executor or ReliableToolExecutor()
        self.tool_context = tool_context or RunToolContext.for_run()

    def rerank(self, query: str, candidates: list[RetrievalCandidate], top_n: int) -> RerankResult:
        estimated_tokens = _estimated_tokens(query) * len(candidates) + sum(
            _estimated_tokens(candidate.text) for candidate in candidates
        )
        estimate = self.pricing.cost_cny(estimated_tokens)
        self.ledger.reserve_external_call(run_id=self.run_id, estimated_cost_cny=estimate)
        started = time.perf_counter()
        try:
            result = self.executor.execute(
                RAG_RERANK_TOOL_SPEC,
                lambda: _post_json(
                    self.endpoint,
                    {"Authorization": f"Bearer {self.api_key}"},
                    {
                        "model": DASHSCOPE_RERANK_MODEL,
                        "query": query,
                        "documents": [candidate.text for candidate in candidates],
                        "top_n": top_n,
                    },
                ),
                self.tool_context,
            )
            if not result.ok:
                assert result.error is not None
                raise ToolExecutionError(result.error.kind, result.error.message)
            payload = result.value
            assert isinstance(payload, dict)
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
            metadata={
                "candidate_count": len(candidates),
                "tool_error_summary": [event.model_dump(mode="json") for event in self.tool_context.degradation_events],
            },
        )
        _record_retrieval_call(
            call_kind="rerank",
            model=DASHSCOPE_RERANK_MODEL,
            inputs=[query, *(candidate.text for candidate in candidates)],
            dimensions=None,
            token_count=tokens,
            cost_cny=self.pricing.cost_cny(tokens),
            latency_seconds=latency,
        )
        ranked.sort(key=lambda candidate: (-(candidate.rerank_score or 0.0), candidate.chunk_id))
        return RerankResult(ranked[:top_n], len(candidates), tokens, round(latency * 1000))


def _post_json(endpoint: str, headers: dict[str, str], payload: dict[str, object]) -> dict[str, object]:
    response = httpx.post(endpoint, headers=headers, json=payload, timeout=60.0)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("provider response is not an object")
    return value


def _record_retrieval_call(
    *,
    call_kind: str,
    model: str,
    inputs: list[str],
    dimensions: int | None,
    token_count: int,
    cost_cny: float,
    latency_seconds: float,
) -> None:
    recorder = active_trajectory_recorder()
    if recorder is None:
        return
    recorder.record_retrieval_call(
        RetrievalCallTrace(
            call_kind=call_kind,  # type: ignore[arg-type]
            model=model,
            input_hash=hashlib.sha256(
                json.dumps(inputs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            dimensions=dimensions,
            token_count=token_count,
            cost_cny=cost_cny,
            latency_seconds=latency_seconds,
            cache_hit=False,
        )
    )


class EmptyRagSearchTool:
    """Safe pre-index implementation: never fabricates retrieval candidates.

    Its trace is deliberately a compact mapping rather than ``RetrievalTrace``:
    there is no configured index or backend count to report before an index
    exists.  It still carries the same degradation event consumed by manifests.
    """

    fidelity = "fixture"

    def search(
        self,
        *,
        query: str,
        as_of: str,
        context: RunToolContext | None = None,
    ) -> dict[str, object]:
        degradation = DegradationEvent(
            tool="rag_search",
            reason="not_found",
            impact="empty_result",
            attempts=0,
        )
        if context is not None:
            context.degradation_events.append(degradation)
        return {
            "candidates": [],
            "trace": {
                "query": query,
                "as_of": as_of,
                "status": "empty_index",
                "degradation": degradation.model_dump(mode="json"),
            },
        }


class FixtureEmbeddingProvider:
    fidelity = "fixture"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embedding(text) for text in texts]


class CachedEmbeddingProvider:
    """Persistent content-hash cache around an embedding provider.

    The cache is deliberately an ignored runtime artifact: vectors are derived
    from the authoritative corpus and can always be rebuilt.  A process-local
    lock keeps concurrent rebuild batches from corrupting the cache file.
    """

    def __init__(self, *, delegate: EmbeddingProvider, path: Path) -> None:
        self.delegate = delegate
        self.path = path
        self._lock = threading.Lock()
        self._vectors = self._load()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        keys = [_content_hash(text) for text in texts]
        with self._lock:
            missing_by_key = {
                key: text
                for text, key in zip(texts, keys, strict=True)
                if key not in self._vectors
            }
        missing = list(missing_by_key.values())
        if missing:
            vectors = self.delegate.embed(missing)
            if len(vectors) != len(missing):
                raise ValueError("embedding cache delegate returned an incomplete batch")
            with self._lock:
                self._vectors.update(
                    {
                        key: vector
                        for key, vector in zip(missing_by_key, vectors, strict=True)
                    }
                )
                self._write()
        with self._lock:
            return [list(self._vectors[key]) for key in keys]

    def _load(self) -> dict[str, list[float]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        vectors = payload.get("vectors", {})
        if not isinstance(vectors, dict) or not all(
            isinstance(key, str) and isinstance(value, list) and all(isinstance(item, (int, float)) for item in value)
            for key, value in vectors.items()
        ):
            raise ValueError("embedding cache is invalid")
        return {key: [float(item) for item in value] for key, value in vectors.items()}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "vectors": self._vectors}, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    # The provider tokenizes CJK text much more densely than English prose.
    # The real rerank response can charge roughly two tokens per CJK codepoint
    # once its document framing is included.  Reserve at that measured upper
    # bound so the cost-overrun guard remains a circuit breaker, not a normal
    # path for Chinese retrieval.
    cjk = sum("\u3400" <= character <= "\u9fff" for character in text)
    return max(1, 2 * cjk + math.ceil((len(text) - cjk) / 2))
