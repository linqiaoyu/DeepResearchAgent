"""R109: one metric, one line, thirteen restatements of the same figure.

The first live 长江电力 round rendered 指标覆盖状态 for 归母净利润 as a single
1,500-character line holding every matching evidence id: `324.96 亿元` four
times, `32,496,172,808.65 元` four times, `325.2 亿元` five times. Nothing was
wrong with any of them and nothing was readable.

`AGENTS.md` §8 requires acceptance to measure what the reader receives, so the
assertions below count rendered items rather than checking that dedup "is
applied". The evidence shape reproduces that run: three distinct published
figures for 2024 across many sources, and one for 2023.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.agents.reporter import ReporterAgent
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.metric_coverage import evaluate_metric_coverage
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)

FINANCE = load_domain_pack("finance")
METRIC = "归母净利润"
#: (value, unit, period) exactly as the live sources published them.
PUBLISHED = (
    *[("325.2", "亿元", "2024年度")] * 5,
    *[("324.96", "亿元", "2024年")] * 4,
    *[("32496172808.65", "元", "2024年")] * 4,
    ("27244616815.27", "元", "2023年"),
)


class CoverageStatesAFigureOnceTests(unittest.TestCase):
    def _state(self) -> ResearchState:
        state = ResearchState(topic="长江电力2024年度归母净利润")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="fin2024",
                    question="归母净利润是多少？",
                    search_queries=["长江电力 2024 年年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600900",
                            periods=["20231231", "20241231"],
                            metrics=[METRIC],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["fin2024"]
        state.evidence_store = [
            Evidence(
                id=f"e{index}",
                research_id=state.research_id,
                sub_question_id="fin2024",
                claim=f"长江电力{period}归母净利润为{value}{unit}",
                claim_type="data",
                source_kind="text",
                source_url=f"https://example.invalid/{index}",
                source_title=f"来源 {index}",
                extract_text=f"长江电力{period}归母净利润{value}{unit}",
                numeric_fields=NumericFields(
                    entity="长江电力",
                    metric_name=METRIC,
                    period=period,
                    dimension="未标注",
                    value=value,
                    unit=unit,
                ),
            )
            for index, (value, unit, period) in enumerate(PUBLISHED, start=1)
        ]
        return state

    def _coverage_line(self, state: ResearchState) -> str:
        ref_map = {
            evidence.id: index
            for index, evidence in enumerate(state.evidence_store, start=1)
        }
        report = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer()
        )._append_metric_coverage("# 报告\n", state, ref_map)
        return next(
            line
            for line in report.splitlines()
            if line.startswith(f"- {METRIC}")
        )

    def test_the_precondition_is_a_fully_cited_metric(self) -> None:
        coverage = evaluate_metric_coverage(self._state(), FINANCE)

        self.assertEqual(coverage[0].status, "cited")
        self.assertEqual(len(coverage[0].evidence_ids), 14)

    def test_the_reader_gets_one_item_per_published_figure(self) -> None:
        """14 evidence ids, 4 figures: 3 for 2024 and 1 for 2023."""
        line = self._coverage_line(self._state())

        self.assertEqual(line.count("；") + 1, 4)

    def test_a_disagreement_between_sources_still_reaches_the_reader(self) -> None:
        line = self._coverage_line(self._state())

        self.assertIn("325.2 亿元", line)
        self.assertIn("324.96 亿元", line)

    def test_the_precise_filing_figure_is_not_collapsed_into_its_rounding(
        self,
    ) -> None:
        """`324.96 亿元` is a rounding of the 元 figure, not a duplicate of it."""
        line = self._coverage_line(self._state())

        self.assertIn("32,496,172,808.65 元", line)

    def test_no_requested_period_is_dropped_by_deduplication(self) -> None:
        line = self._coverage_line(self._state())

        self.assertIn("27,244,616,815.27 元", line)

    def test_the_line_stays_readable(self) -> None:
        """The measured symptom: the live line was ~1,500 characters."""
        self.assertLess(len(self._coverage_line(self._state())), 600)


if __name__ == "__main__":
    unittest.main()
