from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

from deepresearch_agent.audit_bundle import export_audit_bundle
from deepresearch_agent.provenance import build_run_manifest
from deepresearch_agent.settings import load_settings
from deepresearch_agent.workflow import DeepResearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic fixture research and export a closed audit bundle."
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--as-of", default="2026-07-09")
    parser.add_argument("--structured-output", action="store_true")
    args = parser.parse_args()

    os.environ["DEEPRESEARCH_MODE"] = "deterministic"
    os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_AS_OF"] = args.as_of
    settings = load_settings()
    output_dir = Path(args.output)
    settings = replace(
        settings,
        storage_path=output_dir.parent / "audit_bundle.db",
        runs_root=output_dir.parent / "runs",
        execution_mode="deterministic",
        as_of=date.fromisoformat(args.as_of),
        structured_output_enabled=args.structured_output,
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
    result = export_audit_bundle(
        state=state,
        settings=settings,
        manifest=manifest,
        output_dir=output_dir,
    )
    engine._checkpoint_conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
