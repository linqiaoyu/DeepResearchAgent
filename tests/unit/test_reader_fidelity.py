from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from deepresearch_agent.agents.reporter import ReporterAgent
from deepresearch_agent.domains.finance import FinanceGroundedFactRenderer
from deepresearch_agent.reporting import (
    GroundedFactBatch,
    GroundedReaderClaim,
)
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    StructuredDataRecord,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class ReaderFidelityTests(unittest.TestCase):
    def test_hengrui_missing_digit_is_replaced_by_exact_typed_value(
        self,
    ) -> None:
        state = self._state()
        report = self._mutated_report("6,336,527,14.75")
        reporter = self._reporter()

        guarded = reporter._enforce_reader_fidelity(
            report,
            state,
            self._ref_map(),
        )

        self.assertNotIn("6,336,527,14.75", guarded)
        self.assertIn("6,336,527,014.75元", guarded)
        self.assertIn("7,711,054,811.98元", guarded)
        self.assertIn("同比增长21.69%", guarded)
        self.assertIn("mechanical_grounded_fact", str(reporter.last_stats))

    def test_digit_magnitude_and_decimal_injections_never_reach_reader(
        self,
    ) -> None:
        mutations = {
            "lost_digit": "6,336,527,14.75",
            "one_digit": "6,336,527,014.76",
            "magnitude": "633,652,701.475",
            "decimal": "6,336,527,01475",
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                guarded = self._reporter()._enforce_reader_fidelity(
                    self._mutated_report(mutation),
                    self._state(),
                    self._ref_map(),
                )
                self.assertNotIn(mutation, guarded)
                self.assertIn("6,336,527,014.75元", guarded)
                self.assertIn("未通过 Evidence 保真守卫", guarded)

    def test_grounded_fact_fidelity_failure_degrades_without_raising(
        self,
    ) -> None:
        state = self._state()
        reporter = ReporterAgent(
            grounded_fact_renderer=_MutatingRenderer(),
        )

        guarded = reporter._enforce_reader_fidelity(
            self._mutated_report("6,336,527,14.75"),
            state,
            self._ref_map(),
        )

        self.assertNotIn("2025年归母净利润7,711,054,811.98元", guarded)
        self.assertIn("归母净利润：未取得满足", guarded)
        self.assertIn(
            {
                "tool": "grounded_fact_renderer",
                "impact": "mechanically rendered fact was omitted",
                "attempts": 1,
                "label": "归母净利润",
                "reason": "grounded_fact_fidelity_failure",
            },
            state.metadata["degradation_events"],
        )

    def test_typed_period_wins_over_shared_two_column_extract(self) -> None:
        state = self._state()
        shared_extract = (
            "2025年归母净利润7,711,054,811.98元；"
            "2024年归母净利润6,336,527,014.75元。"
        )
        for evidence in state.evidence_store:
            period = evidence.structured_record.period
            evidence.source_kind = "text"
            evidence.source_tier = "primary"
            evidence.extract_text = shared_extract
            evidence.numeric_fields = NumericFields(
                entity="恒瑞医药",
                metric_name="归母净利润",
                period=period,
                dimension="年度主要会计数据",
                value=evidence.structured_record.value,
                unit="元",
            )
            evidence.structured_record = None

        rendered = FinanceGroundedFactRenderer().render(state).claims

        self.assertEqual(len(rendered), 1)
        self.assertEqual(
            rendered[0].evidence_ids,
            ("profit-2025", "profit-2024"),
        )
        self.assertIn("7711054811.98", rendered[0].text)
        self.assertIn("6336527014.75", rendered[0].text)

    def test_required_contract_without_grounded_facts_hides_llm_numbers(
        self,
    ) -> None:
        state = self._state()
        state.evidence_store = []

        guarded = self._reporter()._enforce_reader_fidelity(
            self._mutated_report("6,336,527,14.75"),
            state,
            {},
        )

        self.assertNotIn("6,336,527,14.75", guarded)
        self.assertIn("归母净利润：未取得满足", guarded)

    def test_public_report_path_invokes_fidelity_guard(self) -> None:
        state = self._state()
        reporter = _CorruptingReporter(
            grounded_fact_renderer=FinanceGroundedFactRenderer(),
        )

        report = reporter.report(state)

        self.assertNotIn("6,336,527,14.75", report)
        self.assertIn("6,336,527,014.75元", report)

    def test_metric_coverage_never_reuses_generated_numeric_claim(
        self,
    ) -> None:
        state = ResearchState(topic="恒瑞医药 2024 年营业收入")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="revenue",
                    question="2024 年营业收入是多少？",
                    search_queries=["600276 2024 年度报告 营业收入"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600276",
                            periods=["2024"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["revenue"]
        state.evidence_store = [
            Evidence(
                id="revenue-2024",
                research_id=state.research_id,
                sub_question_id="revenue",
                claim="2024年营业收入为27,984,605,342.6元。",
                claim_type="data",
                source_kind="text",
                source_url="https://example.invalid/annual-report.pdf",
                source_title="恒瑞医药2024年年度报告",
                source_pub_date=date(2025, 3, 26),
                source_page=6,
                extract_text="营业收入 27,984,605,342.06 27,984,605,342.06",
                numeric_fields=NumericFields(
                    entity="恒瑞医药",
                    metric_name="营业收入",
                    period="2024年",
                    dimension="年度主要会计数据",
                    value=27_984_605_342.06,
                    unit="元",
                ),
            )
        ]

        report = self._reporter().report(state)
        coverage = report.rsplit("## 指标覆盖状态", 1)[1]

        self.assertIn("27984605342.06元", coverage)
        self.assertNotIn("27,984,605,342.6元", coverage)

    def test_reader_text_never_matches_inside_grouped_decimal(self) -> None:
        reporter = self._reporter()
        for value in (
            "27,984,605,342.06元",
            "6,336,527,014.75元",
            "168,838,102,514.79元",
        ):
            with self.subTest(value=value):
                self.assertEqual(reporter._reader_text(value), value)

    def test_empty_generated_key_findings_still_render_required_fact(
        self,
    ) -> None:
        empty = self._mutated_report("6,336,527,14.75").replace(
            (
                "- 2025年归母净利润7,711,054,811.98元，"
                "2024年6,336,527,14.75元，同比增长21.69%。 [^2] [^1]"
            ),
            "",
        )

        guarded = self._reporter()._enforce_reader_fidelity(
            empty,
            self._state(),
            self._ref_map(),
        )

        self.assertIn("7,711,054,811.98元", guarded)
        self.assertIn("6,336,527,014.75元", guarded)

    def test_partial_and_unbound_renderer_batches_fail_closed(self) -> None:
        for renderer, message in (
            (_PartialRenderer(), "partial or ambiguous"),
            (_UnboundRenderer(), "unbound claim"),
        ):
            with self.subTest(renderer=type(renderer).__name__):
                reporter = ReporterAgent(grounded_fact_renderer=renderer)
                with self.assertRaisesRegex(ValueError, message):
                    reporter._enforce_reader_fidelity(
                        self._mutated_report("6,336,527,14.75"),
                        self._state(),
                        self._ref_map(),
                    )

    def test_duplicate_metric_requests_have_distinct_grounded_batch_labels(self) -> None:
        state = self._state()
        duplicate = state.plan.sub_questions[0].model_copy(
            update={"id": "finance-duplicate"}
        )
        state.plan = state.plan.model_copy(
            update={"sub_questions": [*state.plan.sub_questions, duplicate]}
        )

        batch = FinanceGroundedFactRenderer().render(state)

        self.assertEqual(len(batch.required_labels), len(set(batch.required_labels)))
        self.assertIn("finance · 归母净利润", batch.required_labels)
        self.assertIn("finance-duplicate · 归母净利润", batch.required_labels)

    def test_engine_wires_finance_fidelity_policy(self) -> None:
        with TemporaryDirectory() as directory:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(directory) / "research.db"
                )
            )
            try:
                self.assertIsInstance(
                    engine.reporter.grounded_fact_renderer,
                    FinanceGroundedFactRenderer,
                )
            finally:
                engine._checkpoint_conn.close()

    def _reporter(self) -> ReporterAgent:
        return ReporterAgent(
            grounded_fact_renderer=FinanceGroundedFactRenderer(),
        )

    def _ref_map(self) -> dict[str, int]:
        return {"profit-2024": 1, "profit-2025": 2}

    def _mutated_report(self, mutation: str) -> str:
        return "\n".join(
            [
                "# 恒瑞医药",
                "",
                "## 摘要",
                "已按年报核验。",
                "",
                "## 关键发现",
                "",
                (
                    "- 2025年归母净利润7,711,054,811.98元，"
                    f"2024年{mutation}元，同比增长21.69%。 [^2] [^1]"
                ),
                "",
                "## 详细分析",
                "### 利润",
                f"- 归母净利润错误转写仍为{mutation}元。 [^1]",
                "",
                "## 风险与限制",
                "- 无新增数值风险。",
                "",
                "## 未验证假设",
                "- 无。",
                "",
                "## 参考来源",
                "[^1]: AKShare 2024",
                "[^2]: AKShare 2025",
            ]
        )

    def _state(self) -> ResearchState:
        state = ResearchState(
            topic="恒瑞医药 2025 年归母净利润相较 2024 年变化"
        )
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="归母净利润是多少？",
                    search_queries=["600276 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600276",
                            periods=["20251231", "20241231"],
                            metrics=["归母净利润"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["finance"]
        state.evidence_store = [
            self._evidence(
                state,
                "profit-2024",
                "20241231",
                6_336_527_014.75,
            ),
            self._evidence(
                state,
                "profit-2025",
                "20251231",
                7_711_054_811.98,
            ),
        ]
        return state

    def _evidence(
        self,
        state: ResearchState,
        evidence_id: str,
        period: str,
        value: float,
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            research_id=state.research_id,
            sub_question_id="finance",
            claim=f"恒瑞医药 {period} 累计归母净利润为{value}元。",
            claim_type="data",
            source_kind="structured",
            source_url=f"akshare://{evidence_id}",
            source_title=f"AKShare {evidence_id}",
            source_pub_date=date(2026, 7, 26),
            extract_text=f"归母净利润 {period} {value}",
            structured_record=StructuredDataRecord(
                entity="恒瑞医药",
                symbol="600276",
                metric_name="归母净利润",
                period=period,
                dimension="累计",
                value=value,
                unit="元",
                data_source="AKShare",
                as_of=date(2026, 7, 26),
            ),
        )


class _MutatingRenderer:
    def render(self, state: ResearchState) -> GroundedFactBatch:
        del state
        return GroundedFactBatch(
            required_labels=("归母净利润",),
            claims=(
                GroundedReaderClaim(
                    text=(
                        "归母净利润：恒瑞医药 2024年累计归母净利润为"
                        "6,336,527,14.75元。"
                    ),
                    evidence_ids=("profit-2024",),
                    fact_keys=frozenset({("恒瑞医药", "归母净利润", "2024", "累计")}),
                    label="归母净利润",
                ),
            ),
            gaps=(),
        )

    def is_supported(
        self,
        text: str,
        evidence: list[Evidence],
        state: ResearchState,
        *,
        labels: set[str],
    ) -> bool:
        return FinanceGroundedFactRenderer().is_supported(
            text,
            evidence,
            state,
            labels=labels,
        )


class _PartialRenderer(_MutatingRenderer):
    def render(self, state: ResearchState) -> GroundedFactBatch:
        batch = super().render(state)
        return GroundedFactBatch(
            required_labels=("归母净利润", "营业收入"),
            claims=batch.claims,
            gaps=(),
        )


class _UnboundRenderer(_MutatingRenderer):
    def render(self, state: ResearchState) -> GroundedFactBatch:
        batch = super().render(state)
        claim = batch.claims[0]
        return GroundedFactBatch(
            required_labels=batch.required_labels,
            claims=(
                GroundedReaderClaim(
                    text=claim.text,
                    evidence_ids=("missing-evidence",),
                    fact_keys=claim.fact_keys,
                    label=claim.label,
                ),
            ),
            gaps=(),
        )


class _CorruptingReporter(ReporterAgent):
    def __init__(
        self,
        *,
        grounded_fact_renderer: FinanceGroundedFactRenderer,
    ) -> None:
        super().__init__(
            llm_client=object(),  # type: ignore[arg-type]
            grounded_fact_renderer=grounded_fact_renderer,
        )

    def _llm_report(self, state: ResearchState) -> str:
        del state
        return ReaderFidelityTests()._mutated_report("6,336,527,14.75")


if __name__ == "__main__":
    unittest.main()
