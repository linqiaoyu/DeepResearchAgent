from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

from deepresearch_agent.audit_bundle import export_audit_bundle
from deepresearch_agent.provenance import build_run_manifest
from deepresearch_agent.research_snapshot import (
    build_research_snapshot,
    save_research_snapshot,
)
from deepresearch_agent.settings import load_settings
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
    args = parser.parse_args()

    _load_env(Path(args.env_path))
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

    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"output already exists: {output}")
    as_of = date.fromisoformat(args.as_of)
    _configure_mode(args.mode, as_of=args.as_of)
    settings = replace(
        load_settings(),
        storage_path=output / "runtime" / "research.db",
        runs_root=output / "runs",
        execution_mode="llm" if args.mode == "live" else "deterministic",
        as_of=as_of,
        structured_output_enabled=True,
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

    engine = DeepResearchEngine(settings=settings)
    try:
        state = engine.run(topic=args.topic, depth_level=args.depth)
        manifest = build_run_manifest(
            state,
            settings,
            started_at=state.started_at,
            ended_at=state.updated_at,
        )
        structured = state.structured_output or engine.reporter.structured_output(state)
        (output / "report.md").write_text(state.final_report or "", encoding="utf-8")
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
        engine._checkpoint_conn.close()

    print(f"request={output / 'request.json'}")
    print(f"report={output / 'report.md'}")
    print(f"structured={output / 'structured.json'}")
    print(f"structured_table={table_path}")
    print(f"audit_bundle={output / 'audit_bundle'}")
    print(f"audit_citation_closure={audit_result['citation_closure']}")
    print(f"snapshot={snapshot_path}")


def _live_preflight(*, allow_paid_api: bool) -> list[str]:
    missing = []
    for key in ("DEEPSEEK_API_KEY", "TAVILY_API_KEY"):
        if not os.getenv(key, "").strip():
            missing.append(key)
    if not allow_paid_api:
        missing.append("--allow-paid-api (explicit paid-provider confirmation)")
    return missing


def _configure_mode(mode: str, *, as_of: str) -> None:
    os.environ["DEEPRESEARCH_AS_OF"] = as_of
    if mode == "live":
        os.environ["DEEPRESEARCH_MODE"] = "llm"
        os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "tavily"
        os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "akshare"
    else:
        os.environ["DEEPRESEARCH_MODE"] = "deterministic"
        os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "fixture"
        os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "fixture"


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
