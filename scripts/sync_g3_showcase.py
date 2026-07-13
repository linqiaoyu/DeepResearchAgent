"""Synchronize the public G3 showcase metrics from Golden v1.1 release assets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_PATH = ROOT / "data" / "demo" / "g3_showcase.json"
G3_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "g3_judge_v11.json"
CITATION_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "g3_citation_support_3s.json"
AUDIT_PATH = ROOT / "data" / "golden_set" / "v1" / "audit_v11.json"
FREEZE_PATH = ROOT / "data" / "golden_set" / "v1" / "freeze.md"


def main() -> None:
    showcase = _read_json(SHOWCASE_PATH)
    g3 = _read_json(G3_PATH)
    citation = _read_json(CITATION_PATH)
    audit = _read_json(AUDIT_PATH)
    freeze = FREEZE_PATH.read_text(encoding="utf-8")
    as_of = _required_match(r"^retrieval_corpus_as_of:\s*(\d{4}-\d{2}-\d{2})$", freeze)
    if audit["summary"]["counts"] != {"PASS": 76, "DEFECT": 0, "UNCERTAIN": 3}:
        raise SystemExit("audit_v11 is not the frozen four-key release gate")
    if citation["verifier"]["samples_per_question"] != 3:
        raise SystemExit("citation release asset must contain three samples per question")
    g3_by_id = {item["id"]: item for item in g3["results"]}
    citation_by_id = {item["id"]: item for item in citation["results"]}
    for report in showcase["reports"]:
        qid = report["id"]
        release, support = g3_by_id[qid], citation_by_id[qid]
        report["false_premise"] = release["false_premise"]
        report["metrics"] = {
            "weighted_score": release["judge"]["median"]["weighted_score"],
            "citation_support_rate": support["support_rate"],
            "citation_resolution_rate": release["mechanical"]["citation_resolution_rate"],
            "citation_repair_retry_rate": release["mechanical"]["citation_repair_retry_rate"],
            "uncited_claim_rate": release["mechanical"]["uncited_claim_rate"],
        }
    summary = dict(g3["summary"])
    summary["avg_citation_support_rate"] = citation["summary"]["avg_citation_support_rate"]
    showcase.update(
        {
            "version": "g3_showcase_v1.1",
            "as_of": as_of,
            "source_round": str(G3_PATH.relative_to(ROOT)),
            "citation_support_source": str(CITATION_PATH.relative_to(ROOT)),
            "audit_source": str(AUDIT_PATH.relative_to(ROOT)),
            "freeze_source": str(FREEZE_PATH.relative_to(ROOT)),
            "summary": summary,
        }
    )
    showcase["methodology"].update(
        {
            "gold_version": "v1.1",
            "citation_support_samples": 3,
            "citation_support_aggregation": "claim-majority",
            "retrieval_corpus_as_of": as_of,
        }
    )
    SHOWCASE_PATH.write_text(json.dumps(showcase, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"synchronized {SHOWCASE_PATH}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _required_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"freeze metadata missing pattern: {pattern}")
    return match.group(1)


if __name__ == "__main__":
    main()
