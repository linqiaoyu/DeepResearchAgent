"""Validate report/reference hygiene on all 28 successful R149 artifacts."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.agents.reporter import (  # noqa: E402
    prune_reference_list,
    remove_web_template_noise,
    web_template_noise_count,
)
from deepresearch_agent.citations import build_footnote_maps, footnote_key  # noqa: E402
from deepresearch_agent.schemas import Evidence, ResearchState  # noqa: E402

from check_reference_list_hygiene import audit, errors_for  # noqa: E402

PROOF = ROOT / "docs/decisions/155/finance-report-hygiene-proof.json"
SOURCE_REPORTS = ROOT / "artifacts/151/offline"
SOURCE_STATES = ROOT / "artifacts/149"
OUTPUT = ROOT / "artifacts/155/offline"
# This is a tracked, real R149 report used only for the mutation floor.  The
# full 28-report source set is intentionally an ignored run artifact, so a
# clean CI checkout cannot use it for an offline self-test.
REGRESSION_REPORT = ROOT / "tests/fixtures/behavioral/r149_live_q16_report.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duplicate_paragraphs(report: str) -> list[str]:
    paragraphs = [
        re.sub(r"\s+", " ", item.strip())
        for item in re.split(r"\n\s*\n", report)
        if item.strip() and not item.lstrip().startswith("#")
    ]
    counts = Counter(item for item in paragraphs if len(item) >= 20)
    return sorted(item for item, count in counts.items() if count > 1)


def _state_path(identifier: str) -> Path:
    matches = list(SOURCE_STATES.glob(f"shard*/work/{identifier}/state.json"))
    if len(matches) != 1:
        raise ValueError(f"expected one R149 state for {identifier}, got {len(matches)}")
    return matches[0]


def _reference_shape(state: ResearchState) -> dict[str, int]:
    maps = build_footnote_maps(state.evidence_store)
    provider_items = [
        item
        for item in state.evidence_store
        if urlsplit(item.source_url).scheme not in {"", "http", "https"}
    ]
    provider_groups = {footnote_key(item) for item in provider_items}
    provider_footnotes = {maps.evidence_id_to_footnote[item.id] for item in provider_items}
    document_items = [
        item
        for item in state.evidence_store
        if urlsplit(item.source_url).scheme in {"", "http", "https"}
    ]
    document_urls = {item.source_url for item in document_items}
    document_footnotes = {maps.evidence_id_to_footnote[item.id] for item in document_items}
    return {
        "provider_groups": len(provider_groups),
        "provider_footnotes": len(provider_footnotes),
        "document_urls": len(document_urls),
        "document_footnotes": len(document_footnotes),
    }


def build_proof() -> dict[str, Any]:
    reports = sorted(SOURCE_REPORTS.glob("Q??-report.md"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for source in reports:
        identifier = source.name.removesuffix("-report.md")
        state_path = _state_path(identifier)
        state = ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
        original = source.read_text(encoding="utf-8")
        cleaned = prune_reference_list(remove_web_template_noise(original))
        target = OUTPUT / source.name
        target.write_text(cleaned.rstrip() + "\n", encoding="utf-8")
        reference = audit(cleaned)
        shape = _reference_shape(state)
        records.append(
            {
                "id": identifier,
                "source_report": str(source.relative_to(ROOT)),
                "source_sha256": _sha256(source),
                "output_report": str(target.relative_to(ROOT)),
                "output_sha256": _sha256(target),
                "source_template_noise": web_template_noise_count(original),
                "template_noise": web_template_noise_count(cleaned),
                "duplicate_paragraphs": len(duplicate_paragraphs(cleaned)),
                "uncited_references": len(reference["never_cited"]),
                "unresolved_citations": len(reference["unresolved"]),
                **shape,
            }
        )
    defined = sum(
        len(audit((OUTPUT / f"{item['id']}-report.md").read_text())["defined"]) for item in records
    )
    cited = sum(
        len(audit((OUTPUT / f"{item['id']}-report.md").read_text())["cited"]) for item in records
    )
    return {
        "round": 155,
        "status": "passed",
        "source_round": 149,
        "quality_claim": False,
        "records": records,
        "metrics": {
            "successful_recorded_cases": len(records),
            "source_template_noise": sum(item["source_template_noise"] for item in records),
            "template_noise": sum(item["template_noise"] for item in records),
            "duplicate_paragraphs": sum(item["duplicate_paragraphs"] for item in records),
            "uncited_references": sum(item["uncited_references"] for item in records),
            "unresolved_citations": sum(item["unresolved_citations"] for item in records),
            "citation_closure_rate": 1.0
            if defined == cited
            else round(min(defined, cited) / max(defined, cited), 6),
            "provider_groups": sum(item["provider_groups"] for item in records),
            "provider_footnotes": sum(item["provider_footnotes"] for item in records),
            "document_urls": sum(item["document_urls"] for item in records),
            "document_footnotes": sum(item["document_footnotes"] for item in records),
        },
    }


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    metrics = proof.get("metrics")
    records = proof.get("records")
    if proof.get("round") != 155 or proof.get("source_round") != 149:
        failures.append("proof identity must be R155 over R149")
    if proof.get("quality_claim") is not False:
        failures.append("offline hygiene proof cannot claim product quality")
    if not isinstance(records, list) or len(records) != 28:
        failures.append("proof must include exactly 28 successful recorded cases")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    for name in (
        "template_noise",
        "duplicate_paragraphs",
        "uncited_references",
        "unresolved_citations",
    ):
        if metrics.get(name) != 0:
            failures.append(f"{name} must equal 0, got {metrics.get(name)!r}")
    if metrics.get("citation_closure_rate") != 1.0:
        failures.append("citation_closure_rate must equal 1.0")
    if (
        not isinstance(metrics.get("source_template_noise"), int)
        or metrics["source_template_noise"] < 1
    ):
        failures.append("proof must reject at least one real source report with template noise")
    if metrics.get("provider_groups") != metrics.get("provider_footnotes"):
        failures.append("provider series were fragmented or over-merged")
    if metrics.get("document_urls") != metrics.get("document_footnotes"):
        failures.append("independent documents were merged")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("finance_report_hygiene_self_test=FAIL shipped proof is dirty")
    metrics = proof["metrics"]
    mutations = {
        name: {**proof, "metrics": {**metrics, name: value}}
        for name, value in {
            "template_noise": 1,
            "duplicate_paragraphs": 1,
            "uncited_references": 1,
            "unresolved_citations": 1,
            "citation_closure_rate": 0.99,
            "provider_footnotes": metrics["provider_footnotes"] + 1,
            "document_footnotes": metrics["document_footnotes"] - 1,
        }.items()
    }
    for name, mutation in mutations.items():
        if not evaluate(mutation):
            raise SystemExit(f"finance_report_hygiene_self_test=FAIL accepted {name}")
    real = REGRESSION_REPORT.read_text(encoding="utf-8")
    if web_template_noise_count(real) < 1:
        raise SystemExit("finance_report_hygiene_self_test=FAIL Q16 no longer proves regression")
    if not errors_for("body [^9]\n\n## 参考来源\n[^1]: unused"):
        raise SystemExit("finance_report_hygiene_self_test=FAIL citation mutation escaped")
    duplicate = "paragraph long enough to be meaningful\n\nparagraph long enough to be meaningful"
    if not duplicate_paragraphs(duplicate):
        raise SystemExit("finance_report_hygiene_self_test=FAIL duplicate mutation escaped")
    # Explicit controls: one provider series aggregates; two documents do not.
    base = Evidence(
        id="one",
        research_id="r",
        sub_question_id="q",
        claim="claim",
        claim_type="data",
        source_title="Provider: close",
        source_url="provider://close/1",
        extract_text="claim",
    )
    series = [base, base.model_copy(update={"id": "two", "source_url": "provider://close/2"})]
    documents = [
        base.model_copy(update={"id": "doc-a", "source_url": "https://a.test/report"}),
        base.model_copy(update={"id": "doc-b", "source_url": "https://b.test/report"}),
    ]
    if len(build_footnote_maps(series).unique_refs) != 1:
        raise SystemExit("finance_report_hygiene_self_test=FAIL provider control fragmented")
    if len(build_footnote_maps(documents).unique_refs) != 2:
        raise SystemExit("finance_report_hygiene_self_test=FAIL document control merged")
    print(f"finance_report_hygiene_self_test=PASS cases={len(mutations) + 6}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--mutation",
        choices=("template-noise", "duplicate-paragraph", "uncited-reference"),
    )
    args = parser.parse_args()
    proof = build_proof() if args.build else json.loads(PROOF.read_text(encoding="utf-8"))
    if args.build:
        PROOF.parent.mkdir(parents=True, exist_ok=True)
        PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.mutation:
        field = {
            "template-noise": "template_noise",
            "duplicate-paragraph": "duplicate_paragraphs",
            "uncited-reference": "uncited_references",
        }[args.mutation]
        proof["metrics"][field] = 1
    if args.self_test:
        _self_test(proof)
    failures = evaluate(proof)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(json.dumps(proof["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
