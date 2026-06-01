from __future__ import annotations

import argparse
import json

from deepresearch_agent.evaluation import EvaluationHarness
from deepresearch_agent.settings import project_root
from deepresearch_agent.workflow import DeepResearchEngine


DEFAULT_TOPIC = "AI Agent 在财富管理行业的落地机会研究"


def run_demo() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--output", default="artifacts/demo_report.md")
    args = parser.parse_args()

    engine = DeepResearchEngine()
    state = engine.run(topic=args.topic, depth_level=args.depth)
    output_path = project_root() / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(state.final_report or "", encoding="utf-8")
    print(f"research_id={state.research_id}")
    print(f"phase={state.current_phase} status={state.status}")
    print(f"report={output_path}")
    if state.evaluation:
        print(state.evaluation.model_dump_json(indent=2))


def run_eval() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", default="artifacts/evaluation/latest_metrics.json")
    args = parser.parse_args()

    summary = EvaluationHarness().run(limit=args.limit)
    output_path = project_root() / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_demo()
