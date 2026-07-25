from __future__ import annotations

import unittest
import tempfile
from datetime import date
from pathlib import Path

from deepresearch_agent.agents import CriticAgent
from deepresearch_agent.orchestration import (
    SufficiencyThresholds,
    build_decision_context,
    evaluate_research_sufficiency,
    refine_research_plan,
)
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


def _evidence(
    item_id: str,
    metric: str,
    value: float,
    *,
    period: str = "2024",
    scope: str = "全年",
    unit: str = "亿元",
) -> Evidence:
    return Evidence(
        id=item_id,
        research_id="numeric-run",
        sub_question_id="finance",
        claim=f"{metric}={value}{unit}",
        claim_type="data",
        source_kind="structured",
        source_url=f"fixture://numeric/{item_id}",
        source_title=item_id,
        source_pub_date=date(2026, 7, 24),
        extract_text=f"{metric}={value}{unit}",
        confidence=0.98,
        numeric_fields=NumericFields(
            entity="样例公司",
            metric_name=metric,
            period=period,
            dimension=scope,
            value=value,
            unit=unit,
        ),
    )


def _state(*evidence: Evidence) -> ResearchState:
    state = ResearchState(topic="数值自洽")
    state.plan = ResearchPlan(
        topic=state.topic,
        sub_questions=[
            SubQuestion(
                id="finance",
                question="核验财务关系",
                search_queries=["fixture"],
            )
        ],
    )
    state.evidence_store = list(evidence)
    return state


def _numeric_issues(state: ResearchState):
    report = CriticAgent(
        today=date(2026, 7, 24),
        numeric_check_enabled=True,
    ).critique(state)
    return (
        [
            issue
            for issue in report.issues
            if issue.issue_type == "numeric_inconsistency"
        ],
        report,
    )


class NumericConsistencyTest(unittest.TestCase):
    def test_complete_growth_relationship_triggers_a_numeric_check(
        self,
    ) -> None:
        state = _state(
            _evidence(
                "growth",
                "营业收入同比增长率",
                20,
                unit="%",
            ),
            _evidence("current", "营业收入", 120),
            _evidence("prior", "营业收入", 100, period="2023"),
        )

        issues, _report = _numeric_issues(state)

        self.assertEqual(issues, [])
        checks = [
            item
            for item in state.agent_decisions
            if item.decision_type == "numeric_consistency_check"
        ]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].inputs["relationship"], "growth_rate")
        self.assertEqual(checks[0].outcome, "pass")
        scan = next(
            item
            for item in state.agent_decisions
            if item.decision_type == "numeric_consistency_scan"
        )
        self.assertEqual(scan.inputs["check_count"], 1)

    def test_detects_wrong_growth_rate_from_two_absolute_periods(self) -> None:
        state = _state(
            _evidence(
                "growth",
                "营收同比增长率",
                25,
                unit="%",
            ),
            _evidence("current", "营业收入", 120),
            _evidence("prior", "营收", 100, period="2023"),
        )

        issues, report = _numeric_issues(state)

        issue = issues[0]
        self.assertEqual(issue.claimed_value, 25)
        self.assertEqual(issue.calculated_value, 20)
        self.assertIn("(120.0-100.0)", issue.formula or "")
        self.assertEqual(
            issue.evidence_ids,
            ["growth", "current", "prior"],
        )
        self.assertIn(issue.suggested_retry_task, report.retry_tasks)

    def test_detects_wrong_share(self) -> None:
        state = _state(
            _evidence(
                "share",
                "海外收入占营业收入占比",
                40,
                unit="%",
            ),
            _evidence("overseas", "海外收入", 30),
            _evidence("revenue", "营业收入", 100),
        )

        issues, _report = _numeric_issues(state)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].calculated_value, 30)
        self.assertIn("3000000000.0/10000000000.0", issues[0].formula or "")

    def test_detects_wrong_total_from_components(self) -> None:
        state = _state(
            _evidence(
                "total",
                "营业收入=国内收入+海外收入",
                120,
            ),
            _evidence("domestic", "国内收入", 80),
            _evidence("overseas", "海外收入", 30),
        )

        issues, _report = _numeric_issues(state)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].calculated_value, 110)
        self.assertEqual(issues[0].formula, "80.0+30.0")

    def test_detects_wrong_currency_unit_conversion(self) -> None:
        state = _state(
            _evidence("billion", "资本开支", 1, unit="亿元"),
            _evidence("ten_thousand", "资本支出", 9000, unit="万元"),
        )

        issues, _report = _numeric_issues(state)

        unit_issue = next(
            issue
            for issue in issues
            if "unit_conversion" in issue.message
        )
        self.assertEqual(unit_issue.claimed_value, 1)
        self.assertEqual(unit_issue.calculated_value, 0.9)

    def test_percentage_decimal_conversion_passes(self) -> None:
        state = _state(
            _evidence("percent", "毛利率", 50, unit="%"),
            _evidence("decimal", "毛利率", 0.5, unit="decimal"),
        )

        issues, _report = _numeric_issues(state)

        self.assertEqual(issues, [])
        check = next(
            item
            for item in state.agent_decisions
            if item.decision_type == "numeric_consistency_check"
        )
        self.assertEqual(check.outcome, "pass")
        self.assertEqual(check.inputs["calculated_value"], 50)

    def test_tolerance_and_rounding_boundary_do_not_false_positive(self) -> None:
        state = _state(
            _evidence(
                "growth",
                "营业收入同比增长率",
                20.01,
                unit="%",
            ),
            _evidence("current", "营收", 120),
            _evidence("prior", "营业收入", 100, period="2023"),
        )

        issues, _report = _numeric_issues(state)

        self.assertEqual(issues, [])
        checks = [
            item
            for item in state.agent_decisions
            if item.decision_type == "numeric_consistency_check"
        ]
        self.assertEqual(checks[0].outcome, "pass")
        self.assertEqual(checks[0].inputs["relative_tolerance"], 0.01)

    def test_cross_scope_is_not_checked_and_emits_scope_conflict(self) -> None:
        state = _state(
            _evidence(
                "share",
                "海外收入占营业收入占比",
                40,
                unit="%",
                scope="全年",
            ),
            _evidence("overseas", "海外收入", 30, scope="全年"),
            _evidence("revenue", "营业收入", 100, scope="单季"),
        )

        issues, report = _numeric_issues(state)

        self.assertEqual(issues, [])
        scope_issues = [
            item
            for item in report.issues
            if item.issue_type == "numeric_conflict"
            and item.message.startswith("Scope conflict")
        ]
        self.assertEqual(len(scope_issues), 1)
        decision = next(
            item
            for item in state.agent_decisions
            if item.decision_type == "numeric_consistency_check"
        )
        self.assertEqual(decision.outcome, "skip_scope_conflict")

    def test_numeric_issue_requires_all_audit_fields_and_decision_is_visible(
        self,
    ) -> None:
        state = _state(
            _evidence(
                "growth",
                "营业收入同比增长率",
                99,
                unit="%",
            ),
            _evidence("current", "营收", 120),
            _evidence("prior", "营业收入", 100, period="2023"),
        )

        issues, _report = _numeric_issues(state)

        payload = issues[0].model_dump(mode="json")
        for field in (
            "claimed_value",
            "calculated_value",
            "formula",
            "evidence_ids",
        ):
            self.assertTrue(payload[field] is not None)
        decisions = [
            item
            for item in state.agent_decisions
            if item.decision_type == "numeric_consistency_check"
        ]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].outcome, "numeric_inconsistency")

    def test_switch_off_records_no_numeric_decisions(self) -> None:
        state = _state(
            _evidence(
                "growth",
                "营业收入同比增长率",
                99,
                unit="%",
            ),
            _evidence("current", "营收", 120),
            _evidence("prior", "营业收入", 100, period="2023"),
        )

        report = CriticAgent(
            today=date(2026, 7, 24),
            numeric_check_enabled=False,
        ).critique(state)

        self.assertFalse(
            any(
                item.issue_type == "numeric_inconsistency"
                for item in report.issues
            )
        )
        self.assertEqual(state.agent_decisions, [])

    def test_numeric_issue_enters_context_and_targets_replanning(self) -> None:
        state = _state(
            _evidence(
                "growth",
                "营业收入同比增长率",
                99,
                unit="%",
            ),
            _evidence("current", "营收", 120),
            _evidence("prior", "营业收入", 100, period="2023"),
        )
        state.critic_report = CriticAgent(
            today=date(2026, 7, 24),
            numeric_check_enabled=True,
        ).critique(state)
        sufficiency = evaluate_research_sufficiency(
            state,
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        context = build_decision_context(
            state,
            iteration=2,
            sufficiency=sufficiency,
        )

        refined = refine_research_plan(
            state,
            sufficiency,
            as_of=date(2026, 7, 24),
            iteration=2,
            decision_context=context,
        )

        self.assertTrue(
            any(
                "官方数据 计算口径 单位 核验" in query
                for query in refined["finance"]
            )
        )

    def test_enabled_engine_critic_node_passes_decision_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                storage_path=Path(temp_dir) / "research.db",
                runs_root=Path(temp_dir) / "runs",
                run_manifest_enabled=False,
                structured_logging_enabled=False,
                max_critic_iter=1,
                numeric_check_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings)
            state = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()

        self.assertTrue(
            any(
                item.decision_type == "numeric_consistency_scan"
                for item in state.agent_decisions
            )
        )


if __name__ == "__main__":
    unittest.main()
