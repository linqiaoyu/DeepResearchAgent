from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from deepresearch_agent.audit_bundle import AuditBundleError, export_audit_bundle
from deepresearch_agent.provenance import build_run_manifest
from deepresearch_agent.schemas import (
    Evidence,
    ResearchState,
    Source,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.structured_output import build_structured_output


def audit_state(*, invalid_citation: bool = False) -> ResearchState:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    evidence = Evidence(
        id="evidence-1",
        research_id="audit-run",
        sub_question_id="q1",
        claim="Verified claim",
        claim_type="fact",
        source_url="https://example.com/source",
        source_title="Example source",
        source_pub_date=date(2026, 7, 8),
        extract_text="Verified claim verbatim.",
        confidence=0.9,
        extracted_at=now,
    )
    citation = "[^99]" if invalid_citation else "[^1]"
    state = ResearchState(
        research_id="audit-run",
        topic="Audit fixture question",
        evidence_store=[evidence],
        sources=[
            Source(
                id="source-1",
                title="Example source",
                url="https://example.com/source",
                source_type="official",
                published_at=date(2026, 7, 8),
                content="Verified claim verbatim.",
                credibility=0.95,
            )
        ],
        final_report=(
            "# Audit fixture question\n\n"
            "## 摘要\n"
            "A fixture-only conclusion.\n\n"
            "## 关键发现\n"
            f"- Verified claim {citation}\n"
        ),
        token_used=42,
        cost_used=0.0,
        started_at=now,
        updated_at=now,
    )
    state.structured_output = build_structured_output(state)
    return state


class AuditBundleTests(unittest.TestCase):
    def test_bundle_is_complete_closed_and_deterministic(self) -> None:
        state = audit_state()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "audit.db",
                as_of=date(2026, 7, 9),
                structured_output_enabled=True,
            )
            manifest = build_run_manifest(
                state,
                settings,
                started_at=state.started_at,
                ended_at=state.updated_at,
            )
            first = export_audit_bundle(
                state=state,
                settings=settings,
                manifest=manifest,
                output_dir=Path(tmp) / "first",
            )
            second = export_audit_bundle(
                state=state,
                settings=settings,
                manifest=manifest,
                output_dir=Path(tmp) / "second",
            )
            expected = {
                "cover.md",
                "evidence.json",
                "ledger.json",
                "manifest.json",
                "report.json",
                "report.md",
                "structured.json",
                "structured.md",
                "structured.xlsx",
            }
            self.assertEqual(set(first["files"]), expected)
            self.assertEqual(first["citation_closure"], "ok")
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertIn(
                "不构成投资建议",
                (Path(tmp) / "first" / "cover.md").read_text(encoding="utf-8"),
            )

    def test_missing_citation_refuses_bundle_and_lists_missing_ids(self) -> None:
        state = audit_state(invalid_citation=True)
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "audit.db")
            manifest = build_run_manifest(
                state,
                settings,
                started_at=state.started_at,
                ended_at=state.updated_at,
            )
            output = Path(tmp) / "rejected"
            with self.assertRaises(AuditBundleError) as raised:
                export_audit_bundle(
                    state=state,
                    settings=settings,
                    manifest=manifest,
                    output_dir=output,
                )
            self.assertEqual(raised.exception.missing_evidence_ids, ["footnote:99"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
