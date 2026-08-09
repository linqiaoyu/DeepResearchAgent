"""Composition-root factory for the retrieval capability.

R110: every sibling capability reaches the engine through a factory --
`build_search_provider`, `build_structured_data_provider`, and the disclosure
source composed in `capability_setup`. Retrieval did not. `RagSearchService`
was constructed **zero times** anywhere in `src/`; its only construction site
was `scripts/run_research_package.py`, and `capability_setup` substituted
`EmptyRagSearchTool()` whenever a caller passed nothing.

So `RAG_ENABLED=true` through `DeepResearchEngine` could not retrieve anything.
The R109 live A/B arm proves it: `provider_fidelity.rag_search='fixture'`,
degradation `rag_search/not_found/empty_result`, zero candidates, on every case
-- a capability that is on and inert, which is the defect
`validate_capability_invariants` was written for in R109.

The empty implementation is still available, but only when it is asked for by
name. A missing backend is now a refused configuration rather than a silent
downgrade.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from deepresearch_agent.settings import Settings

#: Names that select the real Qdrant-backed hybrid retrieval service.
LIVE_RAG_BACKEND_NAMES = frozenset({"", "qdrant", "live", "real"})
#: Names that select the pre-index implementation, which returns no candidates
#: and records a degradation. Selecting it is a deliberate act.
EMPTY_RAG_BACKEND_NAMES = frozenset({"empty", "pre_index", "none", "fixture"})
#: What a live retrieval backend cannot be built without.
LIVE_RAG_REQUIREMENTS = (
    "DASHSCOPE_API_KEY",
    "DEEPRESEARCH_QDRANT_URL",
    "DEEPRESEARCH_QDRANT_COLLECTION",
    "DEEPRESEARCH_RAG_INDEX_VERSION",
)


class UnsupportedRagBackendError(ValueError):
    """A configured retrieval backend name is not one this build knows."""


def rag_backend_name(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return env.get("DEEPRESEARCH_RAG_BACKEND", "").strip().lower()


def missing_rag_configuration(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Environment a live retrieval backend needs and does not have.

    Deliberately a pure environment read: configuration validation must not
    open a network connection to decide whether a run may start.
    """

    if not settings.rag_enabled:
        return []
    env = os.environ if environ is None else environ
    name = rag_backend_name(env)
    if name in EMPTY_RAG_BACKEND_NAMES:
        return []
    if name not in LIVE_RAG_BACKEND_NAMES:
        raise UnsupportedRagBackendError(
            f"unsupported DEEPRESEARCH_RAG_BACKEND {name!r}; supported: "
            + ", ".join(
                sorted((LIVE_RAG_BACKEND_NAMES | EMPTY_RAG_BACKEND_NAMES) - {""})
            )
        )
    return [item for item in LIVE_RAG_REQUIREMENTS if not env.get(item, "").strip()]


def build_rag_search(
    settings: Settings,
    *,
    retrieval_domain: Any | None = None,
    environ: Mapping[str, str] | None = None,
    ledger_path: Path | None = None,
) -> Any:
    """Return the retrieval capability the configuration actually selects."""

    from deepresearch_agent.rag.retrieval import EmptyRagSearchTool

    env = os.environ if environ is None else environ
    name = rag_backend_name(env)
    if name in EMPTY_RAG_BACKEND_NAMES:
        return EmptyRagSearchTool()
    missing = missing_rag_configuration(settings, env)
    if missing:
        from deepresearch_agent.config_validation import ConfigurationError

        raise ConfigurationError(missing)

    # Imported here so an installation without the optional retrieval stack can
    # still import the engine.
    from deepresearch_agent.llm import LLMClient
    from deepresearch_agent.rag.backends import (
        QdrantDenseBackend,
        StorageLexicalBackend,
    )
    from deepresearch_agent.rag.qdrant_index import QdrantIndex
    from deepresearch_agent.rag.retrieval import (
        DashScopeEmbeddingProvider,
        DashScopeRerankerProvider,
        ProviderPricing,
    )
    from deepresearch_agent.rag.search import RagSearchService
    from deepresearch_agent.storage.sqlite_store import SQLiteStore

    database = Path(
        env.get("DEEPRESEARCH_RAG_DATABASE", "").strip() or settings.storage_path
    )
    if not database.is_file():
        raise FileNotFoundError(f"rag database does not exist: {database}")

    ledger = LLMClient(
        ledger_path=ledger_path
        or Path(
            env.get("DEEPRESEARCH_RAG_LEDGER_PATH", "").strip()
            or "data/runtime/rag_ledger.jsonl"
        ),
        global_ledger_path=settings.llm_ledger_path,
        budget_cny=settings.rag_budget_cny,
        completion_func=lambda **_: {},
    )
    # One live index user's cost must not aggregate into an earlier one's.
    run_id = f"rag-{uuid4()}"
    ledger.start_run(run_id)
    pricing = ProviderPricing(0.5, "aliyun_model_studio_public_20260729")
    store = SQLiteStore(database)
    service = RagSearchService(
        lexical=StorageLexicalBackend(store=store),
        dense=QdrantDenseBackend(
            store=store,
            index=QdrantIndex(
                url=env["DEEPRESEARCH_QDRANT_URL"],
                api_key=env.get("DEEPRESEARCH_QDRANT_API_KEY", ""),
                collection=env["DEEPRESEARCH_QDRANT_COLLECTION"],
            ),
            embedding=DashScopeEmbeddingProvider(
                api_key=env["DASHSCOPE_API_KEY"],
                ledger=ledger,
                run_id=run_id,
                pricing=pricing,
                dimensions=1024,
                max_batch_size=10,
            ),
        ),
        reranker=DashScopeRerankerProvider(
            api_key=env["DASHSCOPE_API_KEY"],
            ledger=ledger,
            run_id=run_id,
            pricing=pricing,
        ),
        retrieval_top_k=settings.retrieval_top_k,
        rerank_top_n=settings.rerank_top_n,
        rerank_enabled=settings.rerank_enabled,
        rerank_fail_open=settings.rerank_fail_open,
        retrieval_domain=retrieval_domain,
        index_version=env["DEEPRESEARCH_RAG_INDEX_VERSION"],
    )
    service.ledger = ledger
    service.ledger_run_id = run_id
    return service
