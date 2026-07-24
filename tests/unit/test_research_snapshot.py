from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from deepresearch_agent.provenance import RunManifest
from deepresearch_agent.research_snapshot import (
    DisplayClaimKey,
    MaterialityRules,
    NormalizedClaimKey,
    ResearchSnapshot,
    SnapshotClaim,
    diff_research_snapshots,
    render_snapshot_diff_markdown,
)
from deepresearch_agent.schemas import (
    ComparisonTable,
    EventTimeline,
    RiskMatrix,
    StructuredResearchOutput,
)


def manifest(*, as_of: date = date(2026, 7, 9), model: str = "model-a") -> RunManifest:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    return RunManifest(
        run_id="run",
        started_at=now,
        ended_at=now,
        model_strings={"reporter": model},
        prompt_hashes={"reporter.md": "abc"},
        retrieval_corpus_as_of=as_of,
        evaluation_as_of=as_of,
        config_hash="config",
        dependency_versions={"pydantic": "2"},
        domain="finance",
        mode="deterministic",
        flags={"RUN_MANIFEST_ENABLED": True},
        token_total=0,
        cost_cny_total=0.0,
    )


def structured() -> StructuredResearchOutput:
    return StructuredResearchOutput(
        comparison_table=ComparisonTable(question="q"),
        event_timeline=EventTimeline(question="q"),
        risk_matrix=RiskMatrix(question="q"),
    )


def claim(
    claim_id: str,
    *,
    metric: str,
    scope: str = "累计",
    value: float | None = None,
    sources: list[str] | None = None,
    confidence: float = 0.8,
    direction: str = "neutral",
    display_key: DisplayClaimKey | None = None,
) -> SnapshotClaim:
    return SnapshotClaim(
        claim_id=claim_id,
        key=NormalizedClaimKey(
            entity="宁德时代",
            metric=metric,
            period="2024",
            scope=scope,
        ),
        display_key=display_key,
        text=f"{metric}-{scope}-{value}",
        value=value,
        unit="亿元" if value is not None else None,
        evidence_ids=[f"e-{claim_id}"],
        source_urls=sources or ["https://example.com/a"],
        confidence=confidence,
        thesis_direction=direction,
    )


def snapshot(
    claims: list[SnapshotClaim],
    *,
    as_of: date = date(2026, 7, 9),
    run_manifest: RunManifest | None = None,
) -> ResearchSnapshot:
    item_manifest = run_manifest or manifest(as_of=as_of)
    return ResearchSnapshot(
        question_id="question-1",
        question="q",
        as_of=as_of,
        claims=claims,
        structured_objects=structured(),
        manifest_ref="manifest",
        manifest=item_manifest,
        flags={"RUN_MANIFEST_ENABLED": True},
    )


class ResearchSnapshotDiffTests(unittest.TestCase):
    def test_detects_all_six_change_categories(self) -> None:
        old = snapshot(
            [
                claim("gone", metric="gone"),
                claim("numeric-old", metric="revenue", value=100.0),
                claim("source-old", metric="source", sources=["old"]),
                claim("confidence-old", metric="confidence", confidence=0.9),
                claim("scope-old", metric="profit", scope="累计", value=50.0),
            ]
        )
        new = snapshot(
            [
                claim("added", metric="added", direction="positive"),
                claim("numeric-new", metric="revenue", value=120.0),
                claim("source-new", metric="source", sources=["new"]),
                claim("confidence-new", metric="confidence", confidence=0.7),
                claim("scope-new", metric="profit", scope="单季", value=40.0),
            ]
        )
        result = diff_research_snapshots(old, new)
        self.assertEqual(
            {item.change_type for item in result.changes},
            {
                "added_claim",
                "disappeared_claim",
                "numeric_change",
                "evidence_replacement",
                "confidence_change",
                "scope_change",
            },
        )

    def test_four_key_matches_numeric_change(self) -> None:
        old = snapshot([claim("old", metric="revenue", value=100.0)])
        new = snapshot([claim("new", metric="revenue", value=105.0)])
        result = diff_research_snapshots(old, new)
        self.assertEqual([item.change_type for item in result.changes], ["numeric_change"])
        self.assertEqual(result.changes[0].key.tuple(), ("宁德时代", "revenue", "2024", "累计"))

    def test_scope_change_is_not_misclassified_as_numeric_change(self) -> None:
        old = snapshot([claim("old", metric="profit", scope="累计", value=100.0)])
        new = snapshot([claim("new", metric="profit", scope="单季", value=20.0)])
        result = diff_research_snapshots(old, new)
        self.assertEqual([item.change_type for item in result.changes], ["scope_change"])

    def test_materiality_threshold_boundary_is_inclusive(self) -> None:
        old = snapshot([claim("old", metric="revenue", value=100.0)])
        new = snapshot([claim("new", metric="revenue", value=110.0)])
        result = diff_research_snapshots(
            old,
            new,
            rules=MaterialityRules(numeric_relative_threshold=0.1),
        )
        self.assertEqual(result.changes[0].materiality, "material")

    def test_manifest_or_as_of_change_triggers_warning(self) -> None:
        old = snapshot([claim("same", metric="same")])
        new = snapshot(
            [claim("same-new", metric="same")],
            as_of=date(2026, 7, 24),
            run_manifest=manifest(as_of=date(2026, 7, 24), model="model-b"),
        )
        result = diff_research_snapshots(old, new)
        self.assertTrue(result.system_change_warning)
        self.assertIn("model_strings", result.system_change_reasons)
        self.assertIn("retrieval_corpus_as_of", result.system_change_reasons)

    def test_identical_manifest_and_as_of_do_not_trigger_warning(self) -> None:
        item_manifest = manifest()
        old = snapshot([claim("same", metric="same")], run_manifest=item_manifest)
        new = snapshot([claim("same-new", metric="same")], run_manifest=item_manifest)
        result = diff_research_snapshots(old, new)
        self.assertFalse(result.system_change_warning)
        self.assertTrue(result.comparable)

    def test_display_key_preserves_writing_without_changing_normalized_key(
        self,
    ) -> None:
        display = DisplayClaimKey(
            entity="wealth management pilot",
            metric="Advisor productivity",
            period="未标注",
            scope="pilot cohort",
        )
        old = snapshot(
            [
                claim(
                    "old",
                    metric="advisorproductivity",
                    scope="pilotcohort",
                    value=18.0,
                    display_key=display,
                )
            ]
        )
        new = snapshot(
            [
                claim(
                    "new",
                    metric="advisorproductivity",
                    scope="pilotcohort",
                    value=20.16,
                    display_key=display,
                )
            ]
        )

        result = diff_research_snapshots(old, new)

        self.assertEqual(
            result.changes[0].key.tuple(),
            ("宁德时代", "advisorproductivity", "2024", "pilotcohort"),
        )
        self.assertEqual(result.changes[0].display_key, display)
        self.assertIn("wealth management pilot", result.changes[0].detail)
        self.assertIn("Advisor productivity", result.changes[0].detail)
        self.assertNotIn(
            "wealthmanagementpilot/advisorproductivity",
            result.changes[0].detail,
        )

    def test_changes_sort_material_first_then_category(self) -> None:
        old = snapshot(
            [
                claim("gone", metric="gone"),
                claim("numeric-old", metric="revenue", value=100.0),
            ]
        )
        new = snapshot(
            [
                claim(
                    "added",
                    metric="added",
                    direction="positive",
                ),
                claim("numeric-new", metric="revenue", value=120.0),
            ]
        )

        result = diff_research_snapshots(old, new)

        self.assertEqual(
            [(item.materiality, item.change_type) for item in result.changes],
            [
                ("material", "added_claim"),
                ("material", "numeric_change"),
                ("minor", "disappeared_claim"),
            ],
        )

    def test_markdown_is_deterministic_and_keeps_all_disclosures(self) -> None:
        old = snapshot([claim("old", metric="revenue", value=100.0)])
        new = snapshot(
            [claim("new", metric="revenue", value=120.0)],
            as_of=date(2026, 7, 24),
            run_manifest=manifest(as_of=date(2026, 7, 24), model="model-b"),
        ).model_copy(
            update={
                "demo_constructed": True,
                "demo_note": "fixture 演示数据，不代表真实市场更新。",
            }
        )
        result = diff_research_snapshots(old, new)

        first = render_snapshot_diff_markdown(result)
        second = render_snapshot_diff_markdown(result)

        self.assertEqual(first, second)
        self.assertIn("🧪 演示数据声明", first)
        self.assertIn("跨越了系统变更", first)
        self.assertIn("跨越项", first)
        self.assertIn("本期共识别 1 项重大变更", result.paste_summary)
        self.assertIn("最重要的是，", result.paste_summary)
        self.assertNotIn("；", result.paste_summary)


if __name__ == "__main__":
    unittest.main()
