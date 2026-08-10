"""Refuse a reference list the reader has no marker for.

R117. R116 measured what the 30 R113 live reports actually delivered: 1269
reference lines, of which the body cited 213. **83% of every reference line on
the page was a line nothing pointed to.** 969 of them were provider-series
records -- one report ran to 766 lines, 736 of them references, of which three
were cited: 242 trading days times three price fields, one reference each.

Two independent causes, both fixed and both checked here:

* ``build_footnote_maps`` keyed footnotes on ``source_url``. That is right for a
  document -- R107 added it so two sentences from one filing share a footnote --
  and wrong for a provider series, where every record carries its own URI. It is
  the same defect R107 fixed, in the source class R107 did not cover, which is
  what AGENTS.md section 8 means by fixing the class rather than the instance.
* ``_enforce_reader_fidelity`` rebuilds the page from the sections it keeps and
  used to copy the reference list across untouched, so a footnote cited only
  from a dropped section survived with nothing pointing at it.

The check is on the delivered artifact, not on either mechanism: every reference
the page defines must be cited by the page, and every marker must resolve.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

_REFERENCES_HEADING = "## 参考来源"
_DEF_RE = re.compile(r"^\[\^(\d+)\]:", re.MULTILINE)
_REF_RE = re.compile(r"\[\^(\d+)\]")


def audit(report: str) -> dict[str, object]:
    head, separator, tail = report.partition(_REFERENCES_HEADING)
    body = head if separator else report
    defined = {int(match) for match in _DEF_RE.findall(tail if separator else "")}
    cited = {int(match) for match in _REF_RE.findall(body)}
    reference_lines = len([line for line in tail.splitlines() if _DEF_RE.match(line)])
    body_lines = len([line for line in body.splitlines() if line.strip()])
    return {
        "defined": sorted(defined),
        "cited": sorted(cited),
        "never_cited": sorted(defined - cited),
        "unresolved": sorted(cited - defined),
        "reference_lines": reference_lines,
        "body_lines": body_lines,
    }


def errors_for(report: str) -> list[str]:
    result = audit(report)
    problems: list[str] = []
    never_cited = result["never_cited"]
    unresolved = result["unresolved"]
    assert isinstance(never_cited, list) and isinstance(unresolved, list)
    if never_cited:
        problems.append(
            f"{len(never_cited)} reference(s) the body never cites: {never_cited}"
        )
    if unresolved:
        problems.append(f"{len(unresolved)} marker(s) with no reference: {unresolved}")
    return problems


def _self_test() -> int:
    failures = 0

    clean = (
        "## 摘要\n见 [^1]。\n\n## 参考来源\n"
        "[^1]: A. https://a.invalid (2026-01-01)\n"
    )
    if errors_for(clean):
        print("[self-test] FAIL: a clean report was rejected", file=sys.stderr)
        failures += 1

    orphan = clean + "[^2]: B. https://b.invalid (2026-01-01)\n"
    problems = errors_for(orphan)
    print(f"[self-test] uncited reference: {problems}")
    if not problems:
        print("[self-test] FAIL: an uncited reference was accepted", file=sys.stderr)
        failures += 1

    dangling = "## 摘要\n见 [^9]。\n\n## 参考来源\n[^1]: A. https://a.invalid (2026-01-01)\n"
    problems = errors_for(dangling)
    print(f"[self-test] unresolved marker: {problems}")
    if not problems:
        print("[self-test] FAIL: an unresolved marker was accepted", file=sys.stderr)
        failures += 1

    # The class this round fixed: a provider series must not become one
    # reference per record.
    from deepresearch_agent.citations import build_footnote_maps
    from deepresearch_agent.schemas import Evidence

    series = [
        Evidence(
            id=f"ev-{day}",
            research_id="hygiene",
            sub_question_id="sq",
            claim=f"day {day}",
            claim_type="data",
            source_title="Provider: series close",
            source_url=f"provider://close/000001/2024{day:04d}/{day:x}",
            extract_text=f"day {day}",
        )
        for day in range(1, 51)
    ]
    references = len(build_footnote_maps(series).unique_refs)
    print(f"[self-test] 50 provider records -> {references} reference(s)")
    if references != 1:
        print(
            f"[self-test] FAIL: a 50-record series produced {references} references",
            file=sys.stderr,
        )
        failures += 1

    documents = [
        item.model_copy(update={"source_url": f"https://a.invalid/{index}"})
        for index, item in enumerate(series[:5])
    ]
    document_references = len(build_footnote_maps(documents).unique_refs)
    print(f"[self-test] 5 distinct documents -> {document_references} reference(s)")
    if document_references != 5:
        print(
            "[self-test] FAIL: distinct documents were merged into one reference",
            file=sys.stderr,
        )
        failures += 1

    print(f"reference_list_self_test={'PASS' if not failures else 'FAIL'} cases=5")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    if args.report is None:
        parser.error("choose --self-test or --report")
    report = args.report.read_text(encoding="utf-8")
    problems = errors_for(report)
    for problem in problems:
        print(f"reference_list_error: {problem}", file=sys.stderr)
    result = audit(report)
    print(
        f"reference_list={'PASS' if not problems else 'FAIL'} "
        f"references={result['reference_lines']} body_lines={result['body_lines']} "
        f"never_cited={len(result['never_cited'])} unresolved={len(result['unresolved'])}"  # type: ignore[arg-type]
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
