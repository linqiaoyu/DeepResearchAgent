from __future__ import annotations

import argparse
from pathlib import Path

from deepresearch_agent.research_snapshot import (
    MaterialityRules,
    diff_research_snapshots,
    load_research_snapshot,
    render_snapshot_diff_json,
    render_snapshot_diff_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two business ResearchSnapshot files."
    )
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--json", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--numeric-threshold", type=float, default=0.1)
    parser.add_argument("--confidence-threshold", type=float, default=0.1)
    args = parser.parse_args()

    old = load_research_snapshot(Path(args.old))
    new = load_research_snapshot(Path(args.new))
    diff = diff_research_snapshots(
        old,
        new,
        rules=MaterialityRules(
            numeric_relative_threshold=args.numeric_threshold,
            confidence_absolute_threshold=args.confidence_threshold,
        ),
    )
    markdown_path = Path(args.markdown)
    json_path = Path(args.json)
    summary_path = Path(args.summary)
    for path in (markdown_path, json_path, summary_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_snapshot_diff_markdown(diff), encoding="utf-8")
    json_path.write_text(render_snapshot_diff_json(diff), encoding="utf-8")
    summary_path.write_text(diff.paste_summary + "\n", encoding="utf-8")
    print(f"changes={len(diff.changes)}")
    print(f"material={sum(1 for item in diff.changes if item.materiality == 'material')}")
    print(f"system_change_warning={diff.system_change_warning}")
    print(f"markdown={markdown_path}")
    print(f"json={json_path}")
    print(f"summary={summary_path}")


if __name__ == "__main__":
    main()
