from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from deepresearch_agent.evaluation import (
    EvaluationHarness,
    compare_metric_summaries,
    format_metric_comparison,
    load_metric_summary,
)
from deepresearch_agent.settings import Settings, load_settings, project_root
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


DEFAULT_TOPIC = "AI Agent 在财富管理行业的落地机会研究"


def run_demo() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--output", default="artifacts/demo_report.md")
    parser.add_argument("--mode", choices=["deterministic", "llm"], default=None)
    args = parser.parse_args()

    settings = load_settings()
    if args.mode:
        settings = replace(settings, execution_mode=args.mode)
    engine = DeepResearchEngine(settings=settings)
    state = engine.run(topic=args.topic, depth_level=args.depth)
    output_path = project_root() / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(state.final_report or "", encoding="utf-8")
    print(f"research_id={state.research_id}")
    print(f"phase={state.current_phase} status={state.status}")
    print(f"report={output_path}")
    if state.evaluation:
        print(state.evaluation.model_dump_json(indent=2))
    if engine.llm_client:
        print(f"llm_ledger_total_cny={engine.llm_client.ledger_total_cny():.6f}")


def run_eval() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", default="artifacts/evaluation/latest_metrics.json")
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument("--baseline-path", default="data/eval_baseline.json")
    parser.add_argument("--quality-drop-threshold", type=float, default=0.001)
    args = parser.parse_args()

    summary = EvaluationHarness().run(limit=args.limit)
    output_path = project_root() / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.compare_baseline:
        baseline_path = project_root() / args.baseline_path
        if not baseline_path.exists():
            raise SystemExit(f"Baseline metrics not found: {baseline_path}")
        baseline = load_metric_summary(baseline_path)
        comparison = compare_metric_summaries(
            current=summary,
            baseline=baseline,
            quality_drop_threshold=args.quality_drop_threshold,
        )
        print(format_metric_comparison(comparison))
        if comparison["status"] == "fail":
            raise SystemExit(1)


def run_checkpoint_demo() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--stop-after-phase", default="extracting")
    parser.add_argument("--storage", default="artifacts/checkpoint_demo/research.db")
    parser.add_argument("--output", default="artifacts/checkpoint_demo/report.md")
    args = parser.parse_args()

    storage_path = _project_path(args.storage)
    output_path = _project_path(args.output)
    settings = Settings(storage_path=storage_path)
    store = SQLiteStore(settings.storage_path)
    engine = DeepResearchEngine(settings=settings, store=store)

    paused = engine.run(
        topic=args.topic,
        depth_level=args.depth,
        stop_after_phase=args.stop_after_phase,
    )
    paused_evidence_count = len(paused.evidence_store)
    checkpoint = engine.load_state(paused.research_id)
    if not checkpoint:
        raise SystemExit(f"Checkpoint not found for research_id={paused.research_id}")

    resumed = engine.run(research_id=paused.research_id, resume=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(resumed.final_report or "", encoding="utf-8")

    print(f"research_id={resumed.research_id}")
    print(f"paused_phase={checkpoint.current_phase} paused_status={checkpoint.status}")
    print(f"paused_evidence_count={paused_evidence_count}")
    print(f"resumed_phase={resumed.current_phase} resumed_status={resumed.status}")
    print(f"final_evidence_count={len(resumed.evidence_store)}")
    print(f"checkpoint_db={storage_path}")
    print(f"report={output_path}")


def _project_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return project_root() / candidate


if __name__ == "__main__":
    run_demo()
