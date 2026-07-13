from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.evaluation.gold_audit import (
    MetricNormalizer,
    audit_questions,
    render_audit_markdown,
    summarize_audit,
)


def main() -> None:
    args = _parse_args()
    questions_path = Path(args.questions)
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    normalizer = MetricNormalizer.from_path(Path(args.normalization))
    rows = audit_questions(payload, normalizer)
    summary = summarize_audit(rows)
    markdown = render_audit_markdown(
        rows,
        title=f"Golden {payload.get('meta', {}).get('version', 'unknown')} four-key audit",
    )

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
    if args.json_output:
        json_output = Path(args.json_output)
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(
                {"summary": summary, "rows": [row.as_dict() for row in rows]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(markdown, end="")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.fail_on_defect and summary["counts"]["DEFECT"]:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Golden must_include slots with the four-key gate.")
    parser.add_argument("--questions", default="data/golden_set/v1/questions.json")
    parser.add_argument("--normalization", default="data/finance_metric_normalization.json")
    parser.add_argument("--output", default="")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--fail-on-defect", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
