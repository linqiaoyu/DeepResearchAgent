from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from deepresearch_agent.audit_bundle import export_audit_bundle
from deepresearch_agent.config_validation import ConfigurationError, validate_required_configuration
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import DASHSCOPE_EMBEDDING_ENDPOINT, DASHSCOPE_RERANK_ENDPOINT
from deepresearch_agent.provenance import build_run_manifest
from deepresearch_agent.rag.backends import QdrantDenseBackend, StorageLexicalBackend
from deepresearch_agent.rag.qdrant_index import QdrantIndex
from deepresearch_agent.rag.retrieval import (
    DashScopeEmbeddingProvider,
    DashScopeRerankerProvider,
    ProviderPricing,
)
from deepresearch_agent.rag.search import RagSearchService
from deepresearch_agent.research_snapshot import (
    build_research_snapshot,
    save_research_snapshot,
)
from deepresearch_agent.settings import load_settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.structured_output import (
    render_structured_json,
    render_structured_markdown,
    write_structured_table,
)
from deepresearch_agent.workflow import DeepResearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build one research package: request, cited report, structured output, "
            "audit bundle, and ResearchSnapshot."
        )
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument(
        "--allow-paid-api",
        action="store_true",
        help="Required explicit confirmation before live providers may be called.",
    )
    parser.add_argument(
        "--rag-database",
        type=Path,
        help="Authoritative SQLite corpus store for an explicitly enabled live RAG run.",
    )
    parser.add_argument(
        "--rag-index-version",
        help="Required Qdrant index version for an explicitly enabled live RAG run.",
    )
    args = parser.parse_args()

    _load_env(Path(args.env_path))
    _configure_mode(args.mode, as_of=args.as_of)
    if args.mode == "live":
        missing = _live_preflight(allow_paid_api=args.allow_paid_api)
        if missing:
            print("Live research preflight failed. Missing requirements:")
            for item in missing:
                print(f"- {item}")
            budget = float(os.getenv("DEEPRESEARCH_LLM_BUDGET_CNY", "3.0"))
            print(
                "Estimated API cost magnitude: single-digit CNY per bounded run; "
                f"configured LLM hard budget is CNY {budget:.2f}. "
                "Provider billing remains authoritative."
            )
            raise SystemExit(2)
    if (args.rag_database is None) != (args.rag_index_version is None):
        raise SystemExit("--rag-database and --rag-index-version must be supplied together")

    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"output already exists: {output}")
    as_of = date.fromisoformat(args.as_of)
    settings = replace(
        load_settings(),
        storage_path=output / "runtime" / "research.db",
        runs_root=output / "runs",
        execution_mode="llm" if args.mode == "live" else "deterministic",
        as_of=as_of,
        structured_output_enabled=True,
        rag_enabled=args.rag_database is not None,
        injection_guard_enabled=True if args.rag_database is not None else load_settings().injection_guard_enabled,
    )

    output.mkdir(parents=True)
    (output / "runtime").mkdir()
    _write_json(
        output / "request.json",
        {
            "topic": args.topic,
            "as_of": args.as_of,
            "depth": args.depth,
            "mode": args.mode,
        },
    )

    rag_search = (
        _build_live_rag_search(
            database=args.rag_database,
            index_version=args.rag_index_version,
            ledger_path=output / "runtime" / "rag_ledger.jsonl",
            global_ledger_path=settings.llm_ledger_path,
            # The live workflow LLM client is capped at CNY 3. Keep this
            # separate RAG adapter inside the registered CNY 15 run ceiling.
            budget_cny=settings.rag_budget_cny,
            retrieval_top_k=settings.retrieval_top_k,
            rerank_top_n=settings.rerank_top_n,
            retrieval_domain=load_domain_pack(settings.domain_pack),
        )
        if args.rag_database is not None
        else None
    )
    engine = DeepResearchEngine(settings=settings, rag_search=rag_search)
    try:
        state = engine.run(topic=args.topic, depth_level=args.depth)
        manifest = build_run_manifest(
            state,
            settings,
            started_at=state.started_at,
            ended_at=state.updated_at,
            llm_config=getattr(engine.llm_client, "config", None),
        )
        structured = state.structured_output or engine.reporter.structured_output(state)
        report = state.final_report or ""
        if rag_search is not None:
            rag_run_id = getattr(rag_search, "ledger_run_id", None)
            rag_ledger = getattr(rag_search, "ledger", None)
            if not isinstance(rag_run_id, str) or not isinstance(rag_ledger, LLMClient):
                raise RuntimeError("live RAG service lacks an auditable ledger run id")
            rag_cost = rag_ledger.aggregate_run(rag_run_id)
            state.metadata["rag_ledger_run_id"] = rag_run_id
            state.metadata["rag_cost_summary"] = rag_cost
            report += (
                "\n\n## Live RAG cost reconciliation\n\n"
                f"- workflow research_id: `{state.research_id}`\n"
                f"- RAG ledger run_id: `{rag_run_id}`\n"
                f"- RAG cost_cny_total: `{rag_cost['cost_cny_total']}`\n"
            )
        (output / "report.md").write_text(report, encoding="utf-8")
        (output / "structured.json").write_text(
            render_structured_json(structured),
            encoding="utf-8",
        )
        (output / "structured.md").write_text(
            render_structured_markdown(structured),
            encoding="utf-8",
        )
        table_path = write_structured_table(structured, output / "structured")
        audit_result = export_audit_bundle(
            state=state,
            settings=settings,
            manifest=manifest,
            output_dir=output / "audit_bundle",
        )
        snapshot = build_research_snapshot(
            state=state,
            settings=settings,
            manifest=manifest,
            as_of=as_of,
        )
        snapshot_path = output / "research_snapshot.json"
        save_research_snapshot(snapshot, snapshot_path)
    finally:
        engine.close()

    print(f"request={output / 'request.json'}")
    print(f"report={output / 'report.md'}")
    print(f"structured={output / 'structured.json'}")
    print(f"structured_table={table_path}")
    print(f"audit_bundle={output / 'audit_bundle'}")
    print(f"audit_citation_closure={audit_result['citation_closure']}")
    print(f"snapshot={snapshot_path}")


def _live_preflight(*, allow_paid_api: bool) -> list[str]:
    try:
        validate_required_configuration(load_settings(), environ=os.environ)
        missing: list[str] = []
    except ConfigurationError as exc:
        missing = list(exc.missing)
    if not allow_paid_api:
        missing.append("--allow-paid-api (explicit paid-provider confirmation)")
    return missing


def _build_live_rag_search(
    *,
    database: Path,
    index_version: str,
    ledger_path: Path,
    global_ledger_path: Path,
    budget_cny: float,
    retrieval_top_k: int,
    rerank_top_n: int,
    retrieval_domain: object | None = None,
) -> RagSearchService:
    """Compose an explicitly requested real RAG capability without changing defaults."""

    required = ("DASHSCOPE_API_KEY", "DEEPRESEARCH_QDRANT_URL", "DEEPRESEARCH_QDRANT_COLLECTION")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise ConfigurationError(missing)
    if not database.is_file():
        raise ValueError(f"rag database does not exist: {database}")
    ledger = LLMClient(
        ledger_path=ledger_path,
        global_ledger_path=global_ledger_path,
        budget_cny=budget_cny,
        completion_func=lambda **_: {},
    )
    run_id = f"rag-e2e-{index_version}"
    ledger.start_run(run_id)
    pricing = ProviderPricing(0.5, "aliyun_model_studio_public_20260729")
    store = SQLiteStore(database)
    qdrant = QdrantIndex(
        url=os.environ["DEEPRESEARCH_QDRANT_URL"],
        api_key=os.getenv("DEEPRESEARCH_QDRANT_API_KEY", ""),
        collection=os.environ["DEEPRESEARCH_QDRANT_COLLECTION"],
    )
    _warn_if_rerank_endpoint_domain_differs()
    service = RagSearchService(
        lexical=StorageLexicalBackend(store=store),
        dense=QdrantDenseBackend(
            store=store,
            index=qdrant,
            embedding=DashScopeEmbeddingProvider(
                api_key=os.environ["DASHSCOPE_API_KEY"],
                ledger=ledger,
                run_id=run_id,
                pricing=pricing,
                dimensions=1024,
                max_batch_size=10,
            ),
        ),
        reranker=DashScopeRerankerProvider(
            api_key=os.environ["DASHSCOPE_API_KEY"], ledger=ledger, run_id=run_id, pricing=pricing
        ),
        retrieval_top_k=retrieval_top_k,
        rerank_top_n=rerank_top_n,
        rerank_enabled=True,
        rerank_fail_open=True,
        retrieval_domain=retrieval_domain,
        index_version=index_version,
    )
    service.ledger = ledger
    service.ledger_run_id = run_id
    return service


def _warn_if_rerank_endpoint_domain_differs() -> None:
    """Warn on endpoint-domain drift while preserving the configured endpoints."""

    embedding_domain = urlsplit(DASHSCOPE_EMBEDDING_ENDPOINT).netloc
    rerank_domain = urlsplit(DASHSCOPE_RERANK_ENDPOINT).netloc
    if embedding_domain != rerank_domain:
        print(
            "warning=rerank_endpoint_domain_mismatch "
            f"embedding={embedding_domain} rerank={rerank_domain}"
        )


def _configure_mode(mode: str, *, as_of: str) -> None:
    os.environ["DEEPRESEARCH_AS_OF"] = as_of
    if mode == "live":
        os.environ["DEEPRESEARCH_MODE"] = "llm"
        os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "tavily"
        os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "akshare"
    else:
        os.environ["DEEPRESEARCH_MODE"] = "deterministic"
        os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "fixture"
        # Fixture orchestration defaults to fixture data, but an explicit
        # structured-provider choice is an intentional zero-LLM probe input.
        os.environ.setdefault("DEEPRESEARCH_STRUCTURED_DATA_PROVIDER", "fixture")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
