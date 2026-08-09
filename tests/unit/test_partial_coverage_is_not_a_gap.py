"""R109: one state, two sections, opposite claims -- both printed.

The archived smoke run `artifacts/109/smoke2/work/Q03` delivered a BYD report
whose 关键发现 read `未取得可引用的原始披露事实` for all four metrics, while the
same report's 指标覆盖状态 read `部分已引用；已覆盖 2024，缺少 2023` for those
same four, each carrying evidence ids and a footnote. The judge scored it 0.0
across every dimension and the full gate was green.

The cause was one condition: `FinanceGroundedFactRenderer.render` rendered a
metric only when coverage was `cited`, so a metric answered for one of two
requested periods was reported to the reader as answered for neither.

The evidence below is that run's shape verbatim: typed `numeric_fields`, no
structured record, `亿元` units, one covered period.
"""

from __future__ import annotations

import re
import unittest

from scripts.check_reader_visible_contract import (
    ReaderContractError,
    validate_coverage_findings_agreement,
)

from deepresearch_agent.agents.reporter import (
    FINANCE_SUMMARY_NO_CITABLE_VALUE,
    FINANCE_SUMMARY_POINTS_TO_FINDINGS,
    ReporterAgent,
)
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
PROFIT_2024 = "402.54"
TOPIC = "比亚迪（002594）2023 与 2024 年归母净利润"


class _PartialCoverageFixture:
    """A metric the run answered for 2024 and not for 2023."""

    def _state(self, *, with_period: bool = True) -> ResearchState:
        state = ResearchState(topic=TOPIC)
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="financial_overview",
                    question="归母净利润两年如何变化？",
                    search_queries=["比亚迪 2024 年年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="002594",
                            periods=["20231231", "20241231"],
                            metrics=["归母净利润"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["financial_overview"]
        state.evidence_store = [self._evidence(state, with_period=with_period)]
        return state

    def _evidence(
        self,
        state: ResearchState,
        *,
        with_period: bool,
    ) -> Evidence:
        claim = f"2024年比亚迪归属于上市公司股东的净利润为{PROFIT_2024}亿元"
        return Evidence(
            id="profit-2024",
            research_id=state.research_id,
            sub_question_id="financial_overview",
            claim=claim,
            claim_type="data",
            source_kind="text",
            source_url="https://www.yicai.com/news/102532048.html",
            source_title="比亚迪2024年净利润增长超3成",
            extract_text=f"比亚迪2024年归母净利润{PROFIT_2024}亿元，同比增长34%。",
            numeric_fields=NumericFields(
                entity="比亚迪",
                metric_name="归母净利润",
                # The run recorded `2024`; dropping it is how a period is
                # matched by prose alone, which carries no fact key.
                period="2024" if with_period else "",
                dimension="未标注",
                value=PROFIT_2024,
                unit="亿元",
            ),
        )

    def _ref_map(self, state: ResearchState) -> dict[str, int]:
        return {
            evidence.id: index
            for index, evidence in enumerate(state.evidence_store, start=1)
        }

    def _draft(self) -> str:
        return "\n".join(
            [
                "# 报告",
                "",
                "## 关键发现",
                "- 归母净利润有所增长。 [^1]",
                "",
                "## 参考来源",
                "[^1]: 第一财经 比亚迪 2024",
            ]
        )

    def _delivered(self, state: ResearchState) -> str:
        """Render both sections the way the pipeline renders them."""

        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer()
        )
        ref_map = self._ref_map(state)
        guarded = reporter._enforce_reader_fidelity(self._draft(), state, ref_map)
        return reporter._append_metric_coverage(guarded, state, ref_map)

    def _section(self, report: str, heading: str) -> str:
        lines = report.splitlines()
        start = lines.index(f"## {heading}")
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        return "\n".join(lines[start:end])


class PartialCoverageIsNotAGapTests(_PartialCoverageFixture, unittest.TestCase):
    def test_the_run_really_is_partially_cited(self) -> None:
        """The precondition: without it this test proves nothing."""
        coverage = evaluate_metric_coverage(self._state(), FINANCE)

        self.assertEqual([item.status for item in coverage], ["partially_cited"])
        self.assertEqual(coverage[0].observed_periods, ["2024"])
        self.assertEqual(coverage[0].missing_periods, ["2023"])

    def test_the_reader_gets_the_period_the_run_covered(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        self.assertEqual(batch.gaps, ())
        claim = next(item for item in batch.claims if item.label == "归母净利润")
        self.assertIn(f"{PROFIT_2024} 亿元", claim.text)
        self.assertEqual(claim.evidence_ids, ("profit-2024",))

    def test_the_reader_is_told_which_period_is_missing(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        claim = next(item for item in batch.claims if item.label == "归母净利润")
        self.assertIn("请求报告期 2023 无可引用披露", claim.text)

    def test_no_year_on_year_is_invented_from_one_period(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        claim = next(item for item in batch.claims if item.label == "归母净利润")
        self.assertNotIn("机械计算同比", claim.text)

    def test_findings_no_longer_deny_what_coverage_cites(self) -> None:
        """The delivered page, read against itself."""
        report = self._delivered(self._state())

        findings = self._section(report, "关键发现")
        coverage = self._section(report, "指标覆盖状态")
        self.assertIn(f"{PROFIT_2024} 亿元", findings)
        self.assertIn("[^1]", findings)
        self.assertNotIn("未取得可引用的原始披露事实", findings)
        self.assertIn("部分已引用；已覆盖 2024，缺少 2023", coverage)

    def test_the_offline_contract_accepts_the_delivered_page(self) -> None:
        """Wires the resident guard to a genuinely generated report."""
        validate_coverage_findings_agreement(self._delivered(self._state()))

    def test_the_guard_rejects_the_defect_it_was_written_for(self) -> None:
        # The R109 line verbatim: a gap notice citing nothing, while the
        # coverage section below it cites the evidence for 2024.
        report = re.sub(
            r"^- 归母净利润：.*$",
            "- 归母净利润：未取得可引用的原始披露事实；可查阅对应年度报告。",
            self._delivered(self._state()),
            count=1,
            flags=re.MULTILINE,
        )

        with self.assertRaises(ReaderContractError) as caught:
            validate_coverage_findings_agreement(report)

        self.assertIn("归母净利润", str(caught.exception))


class SummaryStopsPromisingWhatIsNotThereTests(
    _PartialCoverageFixture,
    unittest.TestCase,
):
    """R109: smoke2 Q01 promised figures two lines above saying it had none.

    `artifacts/109/smoke2/work/Q01/report.md` opens with `具体数值、同比变化与
    出处见下方带脚注的关键发现`, and its 关键发现 holds exactly one line:
    `归母净利润：未取得可引用的原始披露事实`. The pointer is boilerplate the
    reporter substitutes for an unbindable summary; nothing checked that the
    section it points at had anything to point at.
    """

    def _draft_with_summary(self) -> str:
        return "\n".join(
            [
                "# 报告",
                "",
                "## 摘要",
                FINANCE_SUMMARY_POINTS_TO_FINDINGS,
                "",
                "## 关键发现",
                "- 归母净利润有所增长。 [^1]",
                "",
                "## 参考来源",
                "[^1]: 第一财经 比亚迪 2024",
            ]
        )

    def _rendered(self, state: ResearchState) -> str:
        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer()
        )
        return reporter._enforce_reader_fidelity(
            self._draft_with_summary(),
            state,
            self._ref_map(state),
        )

    def _empty_state(self) -> ResearchState:
        state = self._state()
        state.evidence_store = []
        return state

    def test_the_precondition_is_a_run_that_found_nothing(self) -> None:
        coverage = evaluate_metric_coverage(self._empty_state(), FINANCE)

        self.assertEqual([item.status for item in coverage], ["searched_unavailable"])

    def test_a_report_with_no_value_stops_promising_one(self) -> None:
        report = self._rendered(self._empty_state())

        self.assertNotIn(FINANCE_SUMMARY_POINTS_TO_FINDINGS, report)
        self.assertIn(FINANCE_SUMMARY_NO_CITABLE_VALUE, report)

    def test_the_pointer_survives_when_there_is_something_to_point_at(self) -> None:
        report = self._rendered(self._state())

        self.assertIn(FINANCE_SUMMARY_POINTS_TO_FINDINGS, report)
        self.assertIn(f"{PROFIT_2024} 亿元", report)


class UnverifiableIsNotUnfoundTests(unittest.TestCase):
    """R109: the same contradiction, reached by the other road.

    A metric can be fully `cited` and still become a gap, because the fidelity
    guard rejects the rendered claim. That happens whenever a filing's figures
    arrive as bare digit strings from a PDF table -- the excerpt names no
    metric, so nothing can bind the number to it. Both live 长江电力 runs that
    retrieved the filing that way shipped `未取得可引用的原始披露事实` in
    关键发现 above a 指标覆盖状态 listing thirteen cited values.

    Saying "not obtained" about evidence the report goes on to cite is false.
    The extraction defect behind it is diagnosed in `docs/decisions/109`; what
    is fixed here is the report telling the reader something untrue about it.
    """

    METRIC = "归母净利润"
    VALUES = {"2023": "27244616815.27", "2024": "32496172808.65"}

    def _state(self) -> ResearchState:
        state = ResearchState(topic="长江电力2024年度归母净利润")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="fin2024",
                    question="归母净利润两年如何变化？",
                    search_queries=["长江电力 2024 年年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600900",
                            periods=["20231231", "20241231"],
                            metrics=[self.METRIC],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["fin2024"]
        state.evidence_store = [
            Evidence(
                id=f"pdf-{period}",
                research_id=state.research_id,
                sub_question_id="fin2024",
                claim=f"长江电力{period}年归母净利润为{value}元",
                claim_type="data",
                source_kind="text",
                source_url="https://static.cninfo.invalid/1223421172.PDF",
                source_title="1223421172.PDF",
                source_page=5,
                source_tier="primary",
                # The shape the live runs produced: a table cell, naming nothing.
                extract_text=f"{int(float(value)):,}.{value.split('.')[1]}",
                numeric_fields=NumericFields(
                    entity="长江电力",
                    metric_name=self.METRIC,
                    period=period,
                    dimension="未标注",
                    value=value,
                    unit="元",
                ),
            )
            for period, value in self.VALUES.items()
        ]
        return state

    def _delivered(self) -> str:
        state = self._state()
        ref_map = {
            evidence.id: index
            for index, evidence in enumerate(state.evidence_store, start=1)
        }
        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer()
        )
        draft = "\n".join(
            [
                "# 报告",
                "",
                "## 关键发现",
                "- 占位。 [^1]",
                "",
                "## 参考来源",
                "[^1]: 年报",
            ]
        )
        guarded = reporter._enforce_reader_fidelity(draft, state, ref_map)
        return reporter._append_metric_coverage(guarded, state, ref_map)

    def test_the_precondition_is_cited_evidence_that_cannot_be_verified(
        self,
    ) -> None:
        state = self._state()
        coverage = evaluate_metric_coverage(state, FINANCE)
        batch = FINANCE.grounded_fact_renderer().render(state)

        self.assertEqual(coverage[0].status, "cited")
        self.assertEqual([c.label for c in batch.claims], [self.METRIC])

    def test_the_reader_is_not_told_the_disclosure_was_never_obtained(
        self,
    ) -> None:
        report = self._delivered()

        self.assertNotIn("未取得可引用的原始披露事实", report)

    def test_the_reader_is_told_what_actually_happened(self) -> None:
        report = self._delivered()

        self.assertIn("摘录无法与该指标绑定核验", report)
        self.assertIn("指标覆盖状态", report)

    def test_the_page_no_longer_contradicts_itself(self) -> None:
        validate_coverage_findings_agreement(self._delivered())

    def test_a_metric_with_no_evidence_still_says_so(self) -> None:
        """The two gap causes must not collapse into one wording."""
        state = self._state()
        state.evidence_store = []
        ref_map: dict[str, int] = {}
        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer()
        )
        report = reporter._enforce_reader_fidelity(
            "# 报告\n\n## 关键发现\n- 占位。\n",
            state,
            ref_map,
        )

        self.assertIn("未取得可引用的原始披露事实", report)
        self.assertNotIn("摘录无法与该指标绑定核验", report)


class UnattributedPeriodStaysAGapTests(_PartialCoverageFixture, unittest.TestCase):
    """Evidence whose period cannot be typed must not become a covered period."""

    def test_coverage_names_no_period_it_cannot_prove(self) -> None:
        coverage = evaluate_metric_coverage(
            self._state(with_period=False), FINANCE
        )

        self.assertEqual(coverage[0].status, "partially_cited")
        self.assertEqual(coverage[0].observed_periods, [])

    def test_the_metric_stays_a_gap_rather_than_a_floating_number(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(
            self._state(with_period=False)
        )

        self.assertEqual(batch.gaps, ("归母净利润",))
        self.assertEqual(batch.claims, ())


if __name__ == "__main__":
    unittest.main()
