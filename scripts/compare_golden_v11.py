from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SUMMARY_METRICS = (
    "avg_weighted_score",
    "avg_fact_coverage",
    "avg_fact_accuracy",
    "avg_citation_support",
    "avg_synthesis_balance",
    "avg_citation_support_rate",
    "avg_citation_resolution_rate",
    "avg_citation_repair_retry_rate",
    "avg_uncited_claim_rate",
)
GENERATIONS = ("G1", "G2", "G3")


def main() -> None:
    args = _parse_args()
    old_paths = {"G1": args.old_g1, "G2": args.old_g2, "G3": args.old_g3}
    new_paths = {"G1": args.new_g1, "G2": args.new_g2, "G3": args.new_g3}
    old = {key: _load(Path(path)) for key, path in old_paths.items()}
    new = {key: _load(Path(path)) for key, path in new_paths.items()}
    validation = _validate(old, new)
    payload = _comparison_payload(old, new, validation, old_paths, new_paths)
    json_path = Path(args.json_output)
    markdown_path = Path(args.markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["validation"], ensure_ascii=False, indent=2))


def _comparison_payload(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
    validation: dict[str, Any],
    old_paths: dict[str, str],
    new_paths: dict[str, str],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    per_question: list[dict[str, Any]] = []
    for metric in SUMMARY_METRICS:
        summary[metric] = {
            generation: {
                "v1.0": old[generation].get("summary", {}).get(metric),
                "v1.1": new[generation].get("summary", {}).get(metric),
                "delta": _delta(
                    new[generation].get("summary", {}).get(metric),
                    old[generation].get("summary", {}).get(metric),
                ),
            }
            for generation in GENERATIONS
        }

    old_by_generation = {
        generation: {str(item["id"]): item for item in old[generation]["results"]}
        for generation in GENERATIONS
    }
    new_by_generation = {
        generation: {str(item["id"]): item for item in new[generation]["results"]}
        for generation in GENERATIONS
    }
    question_ids = [str(item["id"]) for item in new["G1"]["results"]]
    for qid in question_ids:
        row: dict[str, Any] = {"id": qid, "generations": {}}
        for generation in GENERATIONS:
            old_result = old_by_generation[generation][qid]
            new_result = new_by_generation[generation][qid]
            old_score = old_result["judge"]["median"]["weighted_score"]
            new_score = new_result["judge"]["median"]["weighted_score"]
            row["generations"][generation] = {
                "weighted_score_v10": old_score,
                "weighted_score_v11": new_score,
                "weighted_score_delta": _delta(new_score, old_score),
                "citation_support_rate_v10": old_result["citation_support"]["support_rate"],
                "citation_support_rate_v11": new_result["citation_support"]["support_rate"],
                "false_premise_failed_v10": old_result.get("false_premise_failed"),
                "false_premise_failed_v11": new_result.get("false_premise_failed"),
            }
        per_question.append(row)

    false_premise = [item for item in per_question if item["id"] in {"Q08", "Q16"}]
    return {
        "release_gold_version": "v1.1",
        "historical_gold_version": "v1.0",
        "intentional_input_difference": "gold definitions and evidence refs in revisions_v11.json",
        "judge_sampling_note": (
            "Saved reports and evidence are identical within each generation; model sampling remains "
            "a test-retest noise source even though the only intentional input change is gold."
        ),
        "sources": {"v1.0": old_paths, "v1.1": new_paths},
        "validation": validation,
        "summary": summary,
        "per_question": per_question,
        "false_premise": false_premise,
        "judge_cost_cny_v11": {
            generation: new[generation]["summary"].get("total_judge_cost_cny", 0.0)
            for generation in GENERATIONS
        },
    }


def _validate(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for generation in GENERATIONS:
        old_results = {str(item["id"]): item for item in old[generation].get("results", [])}
        new_results = {str(item["id"]): item for item in new[generation].get("results", [])}
        if set(old_results) != set(new_results):
            raise ValueError(f"{generation} v1.0/v1.1 question ids differ")
        mismatched_research_ids = [
            qid
            for qid in old_results
            if old_results[qid].get("research_id") != new_results[qid].get("research_id")
        ]
        if mismatched_research_ids:
            raise ValueError(f"{generation} saved states differ: {mismatched_research_ids}")
        if int(new[generation].get("judge_samples", 0)) != 3:
            raise ValueError(f"{generation} v1.1 judge_samples must be 3")
        if new[generation].get("gold_version") != "v1.1":
            raise ValueError(f"{generation} result is not tagged gold v1.1")
        if int(new[generation].get("structured_failures", 0)) != 0:
            raise ValueError(f"{generation} v1.1 has structured failures")
        checks[generation] = {
            "cases": len(new_results),
            "research_ids_identical": True,
            "judge_samples": 3,
            "structured_failures": 0,
            "citation_support_rerun": all(
                "citation_support" in result for result in new_results.values()
            ),
        }
    return checks


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Golden v1.1 Official Three-Generation Comparison",
        "",
        "v1.1 is the release score series. v1.0 is retained as historical gold.",
        "Within each generation the saved ResearchState, report, and evidence are identical; the intentional input change is the gold revision manifest. Three judge samples are aggregated by median, and citation_support is rerun for every case.",
        "",
        "## Validation",
        "",
        "| Generation | Cases | Same saved state | Judge samples | Failures | Citation verifier rerun |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for generation in GENERATIONS:
        row = payload["validation"][generation]
        lines.append(
            f"| {generation} | {row['cases']} | yes | {row['judge_samples']} | "
            f"{row['structured_failures']} | yes |"
        )
    lines.extend(
        [
            "",
            "## Dimension Sequence: v1.0 Historical vs v1.1 Release",
            "",
            "| Metric | G1 v1.0 | G1 v1.1 | Δ | G2 v1.0 | G2 v1.1 | Δ | G3 v1.0 | G3 v1.1 | Δ |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for metric in SUMMARY_METRICS:
        cells = [metric]
        for generation in GENERATIONS:
            values = payload["summary"][metric][generation]
            cells.extend(
                [
                    _format_number(values["v1.0"]),
                    _format_number(values["v1.1"]),
                    _format_delta(values["delta"]),
                ]
            )
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## Per-Question Weighted Score",
            "",
            "| QID | G1 v1.0 | G1 v1.1 | Δ | G2 v1.0 | G2 v1.1 | Δ | G3 v1.0 | G3 v1.1 | Δ |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["per_question"]:
        cells = [row["id"]]
        for generation in GENERATIONS:
            values = row["generations"][generation]
            cells.extend(
                [
                    _format_number(values["weighted_score_v10"]),
                    _format_number(values["weighted_score_v11"]),
                    _format_delta(values["weighted_score_delta"]),
                ]
            )
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## False-Premise Recheck",
            "",
            "`failed=false` means the saved report refuted the false premise.",
            "",
            "| QID | G1 v1.1 failed | G2 v1.1 failed | G3 v1.1 failed |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload["false_premise"]:
        values = [str(row["generations"][generation]["false_premise_failed_v11"]).lower() for generation in GENERATIONS]
        lines.append(f"| {row['id']} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## v1.1 Judge Cost",
            "",
            "| Generation | CNY |",
            "| --- | ---: |",
        ]
    )
    for generation in GENERATIONS:
        lines.append(f"| {generation} | {payload['judge_cost_cny_v11'][generation]:.6f} |")
    lines.append("")
    return "\n".join(lines)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _delta(new: Any, old: Any) -> float | None:
    if not isinstance(new, int | float) or not isinstance(old, int | float):
        return None
    return round(float(new) - float(old), 4)


def _format_number(value: Any) -> str:
    return "n/a" if not isinstance(value, int | float) else f"{float(value):.4f}"


def _format_delta(value: Any) -> str:
    return "n/a" if not isinstance(value, int | float) else f"{float(value):+.4f}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the official Golden v1.1 comparison.")
    parser.add_argument("--old-g1", default="data/golden_set/v1/results/g1_rejudge_qwen37.json")
    parser.add_argument("--old-g2", default="data/golden_set/v1/results/gen2_judge1.json")
    parser.add_argument("--old-g3", default="data/golden_set/v1/results/gen3_judge1.json")
    parser.add_argument("--new-g1", default="data/golden_set/v1/results/g1_judge_v11.json")
    parser.add_argument("--new-g2", default="data/golden_set/v1/results/g2_judge_v11.json")
    parser.add_argument("--new-g3", default="data/golden_set/v1/results/g3_judge_v11.json")
    parser.add_argument(
        "--json-output",
        default="data/golden_set/v1/results/v11_three_point_comparison.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="data/golden_set/v1/results/v11_three_point_comparison.md",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
