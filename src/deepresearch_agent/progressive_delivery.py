from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

SECTION_RE = re.compile(r"^## (?P<title>.+)$", re.MULTILINE)
CITATION_RE = re.compile(r"\[\^([^\]]+)\]")
REFERENCE_RE = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)


class ProgressiveDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReportSection:
    index: int
    heading: str
    markdown: str


def split_report_sections(report: str) -> list[ReportSection]:
    """Split a completed report without changing a single byte."""

    matches = list(SECTION_RE.finditer(report))
    if not matches:
        return [ReportSection(index=0, heading="front_matter", markdown=report)]
    sections: list[ReportSection] = []
    if matches[0].start() > 0:
        sections.append(
            ReportSection(
                index=0,
                heading="front_matter",
                markdown=report[: matches[0].start()],
            )
        )
    for match_index, match in enumerate(matches):
        end = (
            matches[match_index + 1].start()
            if match_index + 1 < len(matches)
            else len(report)
        )
        sections.append(
            ReportSection(
                index=len(sections),
                heading=match.group("title").strip(),
                markdown=report[match.start() : end],
            )
        )
    return sections


def publish_report_progress(
    report: str,
    publish: Callable[[ReportSection], None],
) -> list[ReportSection]:
    """Publish ordered API-level progress for an already completed report."""

    sections = split_report_sections(report)
    for section in sections:
        publish(section)
    return sections


def validate_final_report(
    report: str,
    sections: list[ReportSection],
) -> None:
    assembled = "".join(section.markdown for section in sections)
    if assembled != report:
        raise ProgressiveDeliveryError(
            "section reassembly changed the final report"
        )
    referenced = set(CITATION_RE.findall(report))
    defined = set(REFERENCE_RE.findall(report))
    missing = sorted(referenced - defined)
    if missing:
        raise ProgressiveDeliveryError(
            "final citation closure failed; missing references: "
            + ", ".join(missing)
        )
