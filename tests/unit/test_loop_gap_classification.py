"""R120: the loop must not iterate against a gap research cannot close.

`stop_requested` was `sufficiency.sufficient`, so any open gap kept the loop
running. Measured across the 30 R113 states, the gaps were `counterargument` 63,
`unresolved_critic_issues` 41, `freshness` 28, `independent_source_domains` 11,
`requested_metric_coverage` 8, `evidence_count` 6, `average_confidence` 6.

`freshness` is the one no iteration can close. The golden set is evaluated at
2026-07-09 and asks about FY2024, so on those 28 sub-questions the *freshest*
evidence already held is a median 471 days old (min 433). Searching again cannot
make a filing newer.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.orchestration.research_loop import (
    LOOP_DRIVING_GAPS,
    NON_RESEARCHABLE_GAPS,
    ResearchSufficiency,
    SubquestionSufficiency,
)


def _sufficiency(*gap_sets: list[str]) -> ResearchSufficiency:
    items = [
        SubquestionSufficiency(
            sub_question_id=f"sq{index}",
            evidence_count=3,
            independent_source_domains=2,
            average_confidence=0.9,
            unresolved_critic_issues=0,
            missing_counterargument=False,
            requested_metric_count=0,
            covered_metric_count=0,
            sufficient=not gaps,
            gaps=gaps,
        )
        for index, gaps in enumerate(gap_sets)
    ]
    return ResearchSufficiency(
        score=0.5,
        sufficient=all(item.sufficient for item in items),
        by_sub_question=items,
    )


class GapClassificationTests(unittest.TestCase):
    def test_a_freshness_gap_alone_does_not_keep_the_loop_running(self) -> None:
        sufficiency = _sufficiency(["freshness"])
        self.assertFalse(sufficiency.sufficient)
        self.assertTrue(sufficiency.answered)
        self.assertEqual(sufficiency.actionable_gaps, ())

    def test_a_researchable_gap_keeps_the_loop_running(self) -> None:
        sufficiency = _sufficiency(["evidence_count"])
        self.assertFalse(sufficiency.answered)
        self.assertEqual(sufficiency.actionable_gaps, ("evidence_count",))

    def test_a_researchable_gap_beside_freshness_still_counts(self) -> None:
        sufficiency = _sufficiency(["freshness", "requested_metric_coverage"])
        self.assertFalse(sufficiency.answered)
        self.assertEqual(sufficiency.actionable_gaps, ("requested_metric_coverage",))

    def test_no_gaps_means_answered(self) -> None:
        self.assertTrue(_sufficiency([]).answered)

    def test_actionable_gaps_are_deduplicated_and_ordered(self) -> None:
        sufficiency = _sufficiency(
            ["counterargument", "evidence_count"], ["evidence_count"]
        )
        self.assertEqual(
            sufficiency.actionable_gaps, ("counterargument", "evidence_count")
        )

    def test_every_gap_the_evaluator_emits_is_classified(self) -> None:
        """A new gap kind must be classified, not silently ignored by the loop."""

        import inspect

        from deepresearch_agent.orchestration import research_loop

        source = inspect.getsource(research_loop.evaluate_research_sufficiency)
        emitted = set(
            part.strip('"')
            for part in source.split("gaps.append(")[1:]
            for part in [part.split(")")[0]]
        )
        classified = LOOP_DRIVING_GAPS | NON_RESEARCHABLE_GAPS
        self.assertEqual(
            emitted - classified,
            set(),
            f"unclassified gap kinds: {sorted(emitted - classified)}",
        )

    def test_the_two_classes_do_not_overlap(self) -> None:
        self.assertEqual(LOOP_DRIVING_GAPS & NON_RESEARCHABLE_GAPS, frozenset())


if __name__ == "__main__":
    unittest.main()
