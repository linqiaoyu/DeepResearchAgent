from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from deepresearch_agent.memory import (
    ContextWorkingMemory,
    EpisodicMemory,
    EpisodicRecord,
    MemoryScope,
    ProceduralMemory,
    ProceduralQuery,
    ProceduralRecord,
    ProceduralSufficiencyResult,
    SemanticFact,
    SemanticMemory,
    WorkingMemoryWrite,
    WorkingMemoryQuery,
)
from deepresearch_agent.reflection import DeterministicReflectionSignals
from deepresearch_agent.research_snapshot import research_question_id
from deepresearch_agent.research_snapshot import ResearchSnapshot
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "memory_contracts.json"
TOPIC = "AI Agent 在财富管理行业的落地机会研究"


def _record() -> ProceduralRecord:
    return ProceduralRecord(
        question_type="narrative",
        strategy=("official source",),
        sufficiency_result=ProceduralSufficiencyResult(
            score=0.8,
            sufficient=True,
        ),
        reflection_signals=DeterministicReflectionSignals(),
        run_id="run-memory-proof",
        sub_question_id="sq-1",
        iteration=0,
        observed_as_of=date(2026, 8, 11),
        provenance_refs=("run:run-memory-proof",),
    )


def _cross_process_counts(db_path: Path) -> dict[str, int]:
    code = (
        "import json,sys; from pathlib import Path; "
        "from deepresearch_agent.storage import SQLiteStore; "
        "from deepresearch_agent.memory import EpisodicMemory,EpisodicQuery,"
        "ProceduralMemory,ProceduralQuery; "
        "s=SQLiteStore(Path(sys.argv[1])); "
        "print(json.dumps({'episodic':len(EpisodicMemory(store=s).query("
        "EpisodicQuery(question_id=sys.argv[2]))),"
        "'procedural':len(ProceduralMemory(store=s).query("
        "ProceduralQuery(question_type='narrative')).records),"
        "'semantic':len(__import__('deepresearch_agent.memory',"
        "fromlist=['SemanticMemory']).SemanticMemory(store=s).query("
        "__import__('deepresearch_agent.memory',fromlist=['SemanticQuery'])"
        ".SemanticQuery(entity='ContractCo')))}))"
    )
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(db_path),
            research_question_id(TOPIC),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode:
        raise AssertionError(completed.stdout + completed.stderr)
    return json.loads(completed.stdout)


def measure() -> dict[str, int | float]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))["kinds"]
    expected_kinds = {"working", "episodic", "semantic", "procedural"}
    implementations = {
        "working": ContextWorkingMemory(),
        "episodic": EpisodicMemory(),
        "semantic": SemanticMemory(),
        "procedural": ProceduralMemory(),
    }
    lifecycle_matches = sum(
        implementation.lifecycle
        == registry[name]["lifecycles"]["in_memory"]
        for name, implementation in implementations.items()
    )
    scope_coverage = sum(
        set(registry[name]["scope_dimensions"])
        <= set(MemoryScope.model_fields)
        for name in expected_kinds
    )
    provenance_models = {
        "working": {"": WorkingMemoryWrite},
        "episodic": {"": EpisodicRecord, "snapshot": ResearchSnapshot},
        "semantic": {"": SemanticFact},
        "procedural": {"": ProceduralRecord},
    }
    provenance_coverage = 0
    for name in expected_kinds:
        fields_exist = True
        for field_path in registry[name]["provenance_fields"]:
            prefix, separator, field_name = field_path.partition(".")
            model_key = prefix if separator else ""
            target = field_name if separator else prefix
            model = provenance_models[name].get(model_key)
            fields_exist = fields_exist and bool(
                model is not None and target in model.model_fields
            )
        provenance_coverage += int(fields_exist)

    with tempfile.TemporaryDirectory(prefix="memory-lifecycle-") as temp_dir:
        root = Path(temp_dir)
        db_path = root / "memory.db"
        store = SQLiteStore(db_path)
        settings = Settings(
            storage_path=db_path,
            runs_root=root / "runs",
            prior_memory_enabled=True,
            structured_logging_enabled=False,
            max_critic_iter=1,
        )
        with DeepResearchEngine(settings=settings, store=store) as engine:
            engine.run(topic=TOPIC, depth_level=1)
        ProceduralMemory(store=store).write(_record())
        SemanticMemory(store=store).write(
            SemanticFact(
                entity="ContractCo",
                normalized_metric="revenue",
                period="2025",
                scope="annual",
                value=1.0,
                unit="CNY",
                source_urls=["https://example.test/semantic"],
                as_of=date(2026, 3, 20),
                confidence=1.0,
            )
        )
        counts = _cross_process_counts(db_path)

        scoped_a = ProceduralMemory(
            scope=MemoryScope(
                namespace="procedural",
                domain="finance",
                tenant_id="tenant-a",
            ),
            store=store,
        )
        scoped_a.write(_record())
        tenant_leak = len(
            ProceduralMemory(
                scope=MemoryScope(
                    namespace="procedural",
                    domain="finance",
                    tenant_id="tenant-b",
                ),
                store=store,
            ).query(ProceduralQuery(question_type="narrative")).records
        )
        domain_leak = len(
            ProceduralMemory(
                scope=MemoryScope(
                    namespace="procedural",
                    domain="domain-b-test-fixture",
                    tenant_id="tenant-a",
                ),
                store=store,
            ).query(ProceduralQuery(question_type="narrative")).records
        )

    working = ContextWorkingMemory(
        MemoryScope(
            namespace="working",
            domain="finance",
            tenant_id="tenant-a",
            research_id="run-a",
        )
    )
    run_scope_rejected = 0
    try:
        working.query(
            WorkingMemoryQuery(
                research_id="run-b",
                topic="scope probe",
                budget=10,
            )
        )
    except ValueError:
        run_scope_rejected = 1

    persistent_kinds = {
        "episodic": EpisodicMemory(store=SQLiteStore(db_path)).lifecycle,
        "procedural": ProceduralMemory(store=SQLiteStore(db_path)).lifecycle,
        "semantic": SemanticMemory(store=SQLiteStore(db_path)).lifecycle,
    }
    persistent_count = sum(value == "persistent" for value in persistent_kinds.values())
    cross_process_count = sum(counts[name] >= 1 for name in persistent_kinds)
    return {
        "memory_kinds_registered": len(registry),
        "memory_kind_contract_coverage": len(set(registry) & expected_kinds) / 4,
        "truthful_lifecycle_coverage": lifecycle_matches / 4,
        "scope_dimension_coverage": scope_coverage / 4,
        "provenance_as_of_contract_coverage": provenance_coverage / 4,
        "persistent_kinds": persistent_count,
        "cross_process_persistent_kinds": cross_process_count,
        "persistent_cross_process_rate": cross_process_count / persistent_count,
        "namespace_domain_tenant_leaks": tenant_leak + domain_leak,
        "run_scope_rejections": run_scope_rejected,
    }


def validate(metrics: dict[str, int | float]) -> None:
    expected = {
        "memory_kinds_registered": 4,
        "memory_kind_contract_coverage": 1.0,
        "truthful_lifecycle_coverage": 1.0,
        "scope_dimension_coverage": 1.0,
        "provenance_as_of_contract_coverage": 1.0,
        "persistent_kinds": 3,
        "cross_process_persistent_kinds": 3,
        "persistent_cross_process_rate": 1.0,
        "namespace_domain_tenant_leaks": 0,
        "run_scope_rejections": 1,
    }
    failures = [
        f"{name}: expected {target!r}, got {metrics.get(name)!r}"
        for name, target in expected.items()
        if metrics.get(name) != target
    ]
    if failures:
        raise AssertionError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    metrics = measure()
    validate(metrics)
    for name, value in sorted(metrics.items()):
        print(f"{name}={value}")
    print("memory_lifecycle_self_test=PASS cases=10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
