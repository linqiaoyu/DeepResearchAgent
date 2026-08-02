from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

from deepresearch_agent.provenance import build_run_manifest
from deepresearch_agent.research_snapshot import (
    build_demo_followup,
    build_research_snapshot,
    load_research_snapshot,
    save_research_snapshot,
)
from deepresearch_agent.settings import load_settings
from deepresearch_agent.workflow import DeepResearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a versionable business ResearchSnapshot."
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--topic")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--demo-followup-from")
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of)
    output = Path(args.output)

    if args.demo_followup_from:
        baseline = load_research_snapshot(Path(args.demo_followup_from))
        snapshot = build_demo_followup(baseline, as_of=as_of)
        save_research_snapshot(snapshot, output)
        print(f"snapshot={output}")
        print(f"demo_constructed={snapshot.demo_constructed}")
        print(f"claims={len(snapshot.claims)}")
        return
    if not args.topic:
        parser.error("--topic is required unless --demo-followup-from is used")

    os.environ["DEEPRESEARCH_MODE"] = "deterministic"
    os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_AS_OF"] = args.as_of
    settings = load_settings()
    settings = replace(
        settings,
        storage_path=output.parent / "snapshot_business.db",
        runs_root=output.parent / "runs",
        execution_mode="deterministic",
        as_of=as_of,
    )
    engine = DeepResearchEngine(settings=settings)
    state = engine.run(topic=args.topic, depth_level=args.depth)
    manifest = build_run_manifest(
        state,
        settings,
        started_at=state.started_at,
        ended_at=state.updated_at,
        llm_config=getattr(engine.llm_client, "config", None),
    )
    snapshot = build_research_snapshot(
        state=state,
        settings=settings,
        manifest=manifest,
        as_of=as_of,
    )
    save_research_snapshot(snapshot, output)
    engine.close()
    print(f"snapshot={output}")
    print(f"demo_constructed={snapshot.demo_constructed}")
    print(f"claims={len(snapshot.claims)}")


if __name__ == "__main__":
    main()
