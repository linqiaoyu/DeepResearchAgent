"""Run the preregistered R147 real-boundary interoperability probes."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from dotenv import dotenv_values

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm_config import (
    DASHSCOPE_EMBEDDING_MODEL,
    DEFAULT_LLM_CONFIG,
    LLMConfig,
)
from deepresearch_agent.mcp import MCPStdioClient
from deepresearch_agent.rag.backends import QdrantDenseBackend, StorageLexicalBackend
from deepresearch_agent.rag.chunking import CHUNKER_VERSION
from deepresearch_agent.rag.qdrant_index import IndexedChunk, QdrantIndex
from deepresearch_agent.rag.retrieval import DashScopeEmbeddingProvider, ProviderPricing
from deepresearch_agent.rag.search import RagSearchService, RetrievalFilter
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.storage.sqlite_store import SQLiteStore
from deepresearch_agent.tools import CapabilityRegistry, RunToolContext
from deepresearch_agent.tools.capability_registry import RAG_SEARCH_TOOL_SPEC
from deepresearch_agent.trajectory import (
    NodeTransitionTrace,
    ToolCallTrace,
    TrajectoryRecorder,
    TrajectoryTermination,
    trajectory_recording,
    verify_trajectory_offline,
)


ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "tests/fixtures/mcp/independent_stdio_server.py"
PRICE = ProviderPricing(0.5, "aliyun_model_studio_public_20260729")
LLM_BUDGET_CNY = 20.0
RAG_BUDGET_CNY = 10.0
ROUND_FUSE_CNY = 40.0


def _trajectory_request(boundary: str, **details: Any) -> dict[str, Any]:
    return {
        "topic": f"R147 {boundary} interoperability",
        "mode": "live",
        "depth_level": 1,
        "recorded_plan": {},
        "boundary": boundary,
        **details,
    }


def _record(
    *,
    boundary: str,
    probe: int,
    success: bool,
    degraded: bool,
    cost_cny: float,
    latency_seconds: float,
    recorder: TrajectoryRecorder,
    trajectory_path: Path,
) -> dict[str, Any]:
    verification = verify_trajectory_offline(recorder.trajectory)
    return {
        "boundary": boundary,
        "probe": probe,
        "success": success,
        "degraded": degraded,
        "fidelity": "live" if boundary != "mcp" else "real_process",
        "cost_cny": round(cost_cny, 8),
        "latency_seconds": round(latency_seconds, 6),
        "trajectory_recorded": int(
            bool(
                recorder.trajectory.llm_calls
                or recorder.trajectory.embedding_calls
                or recorder.trajectory.tool_calls
                or recorder.trajectory.node_transitions
            )
        ),
        "termination_recorded": int(recorder.trajectory.termination is not None),
        "offline_verified": int(verification.trace_commitment_verified),
        "trajectory": str(trajectory_path.relative_to(ROOT)),
    }


def _llm_probes(output_root: Path) -> list[dict[str, Any]]:
    ledger_path = output_root / "llm-ledger.jsonl"
    client = LLMClient(
        ledger_path=ledger_path,
        global_ledger_path=output_root / "global-ledger.jsonl",
        budget_cny=LLM_BUDGET_CNY,
    )
    records: list[dict[str, Any]] = []
    for probe in range(1, 4):
        run_id = f"r147-llm-{probe}"
        client.start_run(run_id)
        recorder = TrajectoryRecorder(
            run_id=run_id,
            request=_trajectory_request("llm", probe=probe),
        )
        started = time.perf_counter()
        with trajectory_recording(recorder):
            result = client.complete(
                role="planner",
                run_id=run_id,
                messages=[
                    {
                        "role": "user",
                        "content": f"Interoperability probe {probe}. Reply with OK.",
                    }
                ],
            )
        recorder.finalize(manifest_ref=None, artifacts={"probe.json": "{}"})
        path = recorder.write(output_root / f"llm-{probe}-trajectory.json")
        records.append(
            _record(
                boundary="llm",
                probe=probe,
                success=bool(result.content.strip()),
                degraded=False,
                cost_cny=result.cost_cny,
                latency_seconds=time.perf_counter() - started,
                recorder=recorder,
                trajectory_path=path,
            )
        )

    bad_role = replace(
        DEFAULT_LLM_CONFIG.roles["planner"],
        api_base="http://127.0.0.1:9",
        timeout_seconds=1,
    )
    bad_config = LLMConfig(
        timeout_seconds=1,
        max_retries=0,
        repair_retries=0,
        roles={"planner": bad_role},
    )
    failure = LLMClient(
        ledger_path=output_root / "llm-failure-ledger.jsonl",
        global_ledger_path=output_root / "global-ledger.jsonl",
        budget_cny=1.0,
        config=bad_config,
    )
    run_id = "r147-llm-failure"
    failure.start_run(run_id)
    recorder = TrajectoryRecorder(
        run_id=run_id,
        request=_trajectory_request("llm", failure=True),
    )
    started = time.perf_counter()
    try:
        with trajectory_recording(recorder):
            failure.complete(
                role="planner",
                run_id=run_id,
                messages=[{"role": "user", "content": "failure injection"}],
            )
    except Exception as exc:
        recorder.finalize(
            manifest_ref=None,
            artifacts={"probe.json": "{}"},
            termination=TrajectoryTermination(
                status="failed",
                phase="llm_provider",
                error_type=type(exc).__name__,
                error_message="provider unavailable; local harness retained control",
            ),
        )
    else:  # pragma: no cover - invalid loopback endpoint must not succeed
        raise RuntimeError("LLM failure injection unexpectedly succeeded")
    path = recorder.write(output_root / "llm-failure-trajectory.json")
    records.append(
        _record(
            boundary="llm",
            probe=0,
            success=False,
            degraded=True,
            cost_cny=failure.run_total_cny(run_id),
            latency_seconds=time.perf_counter() - started,
            recorder=recorder,
            trajectory_path=path,
        )
    )
    return records


def _rag_service(
    *,
    env: dict[str, str | None],
    output_root: Path,
    run_id: str,
    endpoint: str | None = None,
) -> tuple[RagSearchService, LLMClient, SQLiteStore, str]:
    ledger = LLMClient(
        ledger_path=output_root / "rag-ledger.jsonl",
        global_ledger_path=output_root / "global-ledger.jsonl",
        budget_cny=RAG_BUDGET_CNY,
        completion_func=lambda **_: {},
    )
    ledger.start_run(run_id)
    store = SQLiteStore(ROOT / "data/runtime/047-assets.db")
    qdrant = QdrantIndex(
        url=str(env["DEEPRESEARCH_QDRANT_URL"]),
        api_key=str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or ""),
        collection=str(env["DEEPRESEARCH_QDRANT_COLLECTION"]),
        context=RunToolContext.for_run(max_external_fetch_requests=20),
    )
    index_version = qdrant.observed_index_version()
    kwargs: dict[str, Any] = {}
    if endpoint is not None:
        kwargs["endpoint"] = endpoint
    embedding = DashScopeEmbeddingProvider(
        api_key=str(env["DASHSCOPE_API_KEY"]),
        ledger=ledger,
        run_id=run_id,
        pricing=PRICE,
        dimensions=1024,
        max_batch_size=10,
        tool_context=RunToolContext.for_run(max_external_fetch_requests=10),
        **kwargs,
    )
    service = RagSearchService(
        lexical=StorageLexicalBackend(store=store),
        dense=QdrantDenseBackend(store=store, index=qdrant, embedding=embedding),
        reranker=None,
        retrieval_top_k=20,
        rerank_top_n=8,
        rerank_enabled=False,
        rerank_fail_open=True,
        index_version=index_version,
    )
    return service, ledger, store, index_version


def _rag_probes(env: dict[str, str | None], output_root: Path) -> list[dict[str, Any]]:
    questions = json.loads(
        (ROOT / "data/golden_set/retrieval_v1/questions.json").read_text(
            encoding="utf-8"
        )
    )
    selected = [item for item in questions if item.get("question_type") == "table"][:3]
    corpus = SQLiteStore(ROOT / "data/runtime/047-assets.db").list_ready_chunks(
        as_of="2025-12-31"
    )
    targets = []
    for item in selected:
        label = item["labels"][0]
        match = next(
            (
                chunk
                for chunk in corpus
                if chunk.document_version_id == label["document_version_id"]
                and chunk.char_start < label["char_end"]
                and chunk.char_end > label["char_start"]
            ),
            None,
        )
        if match is None:
            raise RuntimeError(f"RAG self-rank chunk missing for {item['id']}")
        targets.append(match)
    queries = [match.content for match in targets]
    records: list[dict[str, Any]] = []
    if os.environ.get("R147_BOOTSTRAP_RAG") == "1":
        run_id = "r147-rag-bootstrap"
        ledger = LLMClient(
            ledger_path=output_root / "rag-bootstrap-ledger.jsonl",
            global_ledger_path=output_root / "global-ledger.jsonl",
            budget_cny=RAG_BUDGET_CNY,
            completion_func=lambda **_: {},
        )
        ledger.start_run(run_id)
        recorder = TrajectoryRecorder(
            run_id=run_id,
            request=_trajectory_request("rag_bootstrap"),
        )
        embedding = DashScopeEmbeddingProvider(
            api_key=str(env["DASHSCOPE_API_KEY"]),
            ledger=ledger,
            run_id=run_id,
            pricing=PRICE,
            dimensions=1024,
            max_batch_size=10,
            tool_context=RunToolContext.for_run(max_external_fetch_requests=2),
        )
        started = time.perf_counter()
        with trajectory_recording(recorder):
            vectors = embedding.embed(queries)
        index_version = "r147-h2-v1"
        index = QdrantIndex(
            url=str(env["DEEPRESEARCH_QDRANT_URL"]),
            api_key=str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or ""),
            collection=str(env["DEEPRESEARCH_QDRANT_COLLECTION"]),
            context=RunToolContext.for_run(max_external_fetch_requests=20),
        )
        indexed = index.upsert(
            chunks=[
                IndexedChunk(
                    chunk_id=chunk.id,
                    document_version_id=chunk.document_version_id,
                    effective_date=chunk.effective_date,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    vector=vector,
                    source_url=chunk.canonical_url,
                    published_at=chunk.published_at,
                    published_at_source="authoritative_storage",
                    index_version=index_version,
                    entity_id=chunk.entity_id,
                )
                for chunk, vector in zip(targets, vectors, strict=True)
            ],
            model=DASHSCOPE_EMBEDDING_MODEL,
            chunker_version=CHUNKER_VERSION,
            index_version=index_version,
        )
        recorder.record_node_transition(
            NodeTransitionTrace(
                node="qdrant_bootstrap",
                input_summary={"chunks": len(targets)},
                output_summary={"indexed": indexed, "index_version": index_version},
            )
        )
        recorder.finalize(manifest_ref=None, artifacts={"probe.json": "{}"})
        path = recorder.write(output_root / "rag-bootstrap-trajectory.json")
        records.append(
            _record(
                boundary="rag_bootstrap",
                probe=0,
                success=indexed == len(targets),
                degraded=False,
                cost_cny=ledger.run_total_cny(run_id),
                latency_seconds=time.perf_counter() - started,
                recorder=recorder,
                trajectory_path=path,
            )
        )
    for probe, query in enumerate(queries, start=1):
        run_id = f"r147-rag-{probe}"
        service, ledger, store, index_version = _rag_service(
            env=env, output_root=output_root, run_id=run_id
        )
        recorder = TrajectoryRecorder(
            run_id=run_id,
            request=_trajectory_request("rag", probe=probe),
        )
        started = time.perf_counter()
        filters = RetrievalFilter(
            as_of=date(2025, 12, 31),
            index_version=index_version,
        )
        with trajectory_recording(recorder):
            candidates = service.dense.search(
                query=query,
                filters=filters,
                limit=20,
            )
            recorder.record_tool_call(
                ToolCallTrace(
                    tool_spec=RAG_SEARCH_TOOL_SPEC.model_dump(mode="json"),
                    inputs={
                        "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                        "as_of": "2025-12-31",
                        "index_version": index_version,
                    },
                    result={
                        "candidate_ids": [candidate.chunk_id for candidate in candidates],
                        "probe_scope": "dense_boundary",
                    },
                    attempts=1,
                )
            )
        success = bool(candidates)
        recorder.finalize(manifest_ref=None, artifacts={"probe.json": "{}"})
        path = recorder.write(output_root / f"rag-{probe}-trajectory.json")
        records.append(
            _record(
                boundary="rag",
                probe=probe,
                success=success,
                degraded=False,
                cost_cny=ledger.run_total_cny(run_id),
                latency_seconds=time.perf_counter() - started,
                recorder=recorder,
                trajectory_path=path,
            )
        )

    run_id = "r147-rag-failure"
    service, ledger, store, index_version = _rag_service(
        env=env,
        output_root=output_root,
        run_id=run_id,
        endpoint="http://127.0.0.1:9",
    )
    recorder = TrajectoryRecorder(
        run_id=run_id,
        request=_trajectory_request("rag", failure=True),
    )
    started = time.perf_counter()
    with trajectory_recording(recorder):
        result = service.search(
            query="failure injection",
            as_of="2026-07-28",
            filters=RetrievalFilter(
                as_of=date(2026, 7, 28),
                index_version=index_version,
            ),
        )
    degraded = result["trace"].degradation is not None
    recorder.finalize(manifest_ref=None, artifacts={"probe.json": "{}"})
    path = recorder.write(output_root / "rag-failure-trajectory.json")
    records.append(
        _record(
            boundary="rag",
            probe=0,
            success=False,
            degraded=degraded,
            cost_cny=ledger.run_total_cny(run_id),
            latency_seconds=time.perf_counter() - started,
            recorder=recorder,
            trajectory_path=path,
        )
    )
    return records


def _mcp_probes(output_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    environ = dict(os.environ)
    environ["PYTHONPATH"] = str(ROOT / "src")
    for probe in range(1, 4):
        recorder = TrajectoryRecorder(
            run_id=f"r147-mcp-{probe}",
            request=_trajectory_request("mcp", probe=probe),
        )
        registry = CapabilityRegistry()
        client = MCPStdioClient(
            [sys.executable, str(MCP_SERVER), "--server-id", f"r147-{probe}"],
            server_name=f"r147-{probe}",
            request_timeout_s=5,
            environ=environ,
        )
        started = time.perf_counter()
        try:
            with trajectory_recording(recorder):
                client.discover_and_register(
                    registry,
                    ResearchState(topic=f"R147 MCP probe {probe}"),
                    trusted_server=True,
                )
                result = registry.resolve(f"mcp.r147-{probe}.echo").call(
                    {"value": f"probe-{probe}"},
                    allow_paid=True,
                    context=RunToolContext.for_run(max_external_fetch_requests=1),
                )
        finally:
            process = client.process
            client.close()
        closed = process is not None and process.poll() is not None
        recorder.finalize(manifest_ref=None, artifacts={"probe.json": "{}"})
        path = recorder.write(output_root / f"mcp-{probe}-trajectory.json")
        records.append(
            _record(
                boundary="mcp",
                probe=probe,
                success=bool(result.ok and closed),
                degraded=False,
                cost_cny=0.0,
                latency_seconds=time.perf_counter() - started,
                recorder=recorder,
                trajectory_path=path,
            )
        )

    recorder = TrajectoryRecorder(
        run_id="r147-mcp-failure",
        request=_trajectory_request("mcp", failure=True),
    )
    client = MCPStdioClient(
        [
            sys.executable,
            str(MCP_SERVER),
            "--server-id",
            "r147-bad",
            "--bad-protocol",
        ],
        server_name="r147-bad",
        request_timeout_s=2,
        environ=environ,
    )
    started = time.perf_counter()
    try:
        client.connect()
    except Exception as exc:
        recorder.record_node_transition(
            NodeTransitionTrace(
                node="mcp_discovery",
                input_summary={"server": "r147-bad"},
                output_summary={"local_capabilities_retained": True},
                status="failed",
                error_type=type(exc).__name__,
                error_message="protocol negotiation failed",
            )
        )
        recorder.finalize(
            manifest_ref=None,
            artifacts={"probe.json": "{}"},
            termination=TrajectoryTermination(
                status="failed",
                phase="mcp_discovery",
                error_type=type(exc).__name__,
                error_message="external MCP unavailable; local capabilities retained",
            ),
        )
    else:  # pragma: no cover - deliberately bad protocol cannot negotiate
        raise RuntimeError("MCP failure injection unexpectedly succeeded")
    finally:
        process = client.process
        client.close()
    closed = process is not None and process.poll() is not None
    path = recorder.write(output_root / "mcp-failure-trajectory.json")
    record = _record(
        boundary="mcp",
        probe=0,
        success=False,
        degraded=closed,
        cost_cny=0.0,
        latency_seconds=time.perf_counter() - started,
        recorder=recorder,
        trajectory_path=path,
    )
    record["local_capabilities_retained"] = int(closed)
    records.append(record)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--boundary",
        choices=("all", "llm", "rag", "mcp"),
        default="all",
    )
    args = parser.parse_args()
    env = {key: value for key, value in dotenv_values(ROOT / ".env").items()}
    env.update(
        {
            key: value
            for key, value in os.environ.items()
            if value and (key.startswith("DEEPRESEARCH_") or key == "DASHSCOPE_API_KEY")
        }
    )
    required = {
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPRESEARCH_QDRANT_URL",
        "DEEPRESEARCH_QDRANT_COLLECTION",
    }
    missing = sorted(name for name in required if not str(env.get(name) or "").strip())
    if missing:
        raise SystemExit("required provider configuration absent: " + ", ".join(missing))
    output_path = args.output.resolve()
    output_root = output_path.parent
    output_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if args.boundary in {"all", "llm"}:
        records.extend(_llm_probes(output_root))
    if args.boundary in {"all", "rag"}:
        records.extend(_rag_probes(env, output_root))
    if args.boundary in {"all", "mcp"}:
        records.extend(_mcp_probes(output_root))
    total_cost = sum(float(record["cost_cny"]) for record in records)
    payload = {
        "round": 147,
        "boundary_selection": args.boundary,
        "status": "complete",
        "records": records,
        "total_cost_cny": round(total_cost, 8),
        "round_fuse_cny": ROUND_FUSE_CNY,
    }
    if total_cost > ROUND_FUSE_CNY:
        payload["status"] = "fuse_triggered"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "records": len(records),
                "total_cost_cny": payload["total_cost_cny"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
