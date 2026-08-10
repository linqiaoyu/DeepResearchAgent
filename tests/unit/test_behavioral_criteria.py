"""R115: the golden behavioural criteria, and the guard that keeps them real.

The pre-R115 ``false_premise_failed`` could not return ``True`` on frozen data,
so R113 published ``false_premise_failed=0/30`` for a Q16 report whose summary
opens "宁德时代…被比亚迪反超". These tests pin both halves of the repair: the
evaluator's verdict on the reports that were actually produced, and the guard's
refusal of implementations -- including the shipped one -- that cannot separate
them.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from typing import Any

from deepresearch_agent.evaluation import (
    BEHAVIORAL_EVALUATORS,
    BehavioralVerdict,
    evaluate_behavioral,
    false_premise_failed,
    refute_premise_verdict,
)
from deepresearch_agent.evaluation.behavioral import report_body, token_stated
from deepresearch_agent.settings import project_root

FIXTURES = project_root() / "tests" / "fixtures" / "behavioral"
REGISTRY_PATH = project_root() / "data" / "behavioral_criteria.json"


def _guard() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_behavioral_criteria",
        project_root() / "scripts" / "check_behavioral_criteria.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gold(question_id: str) -> dict[str, Any]:
    path = project_root() / "data" / "golden_set" / "v1" / "questions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["questions"]:
        if item["id"] == question_id:
            return dict(item["gold"])
    raise AssertionError(f"unknown question {question_id}")


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class RefutePremiseVerdictTests(unittest.TestCase):
    def test_real_q16_report_that_asserts_the_premise_is_rejected(self) -> None:
        verdict = refute_premise_verdict(
            _fixture("r113_live_q16_report.md"), _gold("Q16")
        )
        self.assertFalse(verdict.satisfied)
        self.assertIn("339.3", verdict.detail)

    def test_real_q08_report_is_rejected_for_the_missing_year_on_year(self) -> None:
        """The absolute revenue is stated; the number that refutes 下滑 is not."""

        verdict = refute_premise_verdict(
            _fixture("r113_live_q08_report.md"), _gold("Q08")
        )
        self.assertFalse(verdict.satisfied)
        self.assertIn("missing 15.66", verdict.detail)

    def test_constructed_refuting_reports_are_accepted(self) -> None:
        for question_id, fixture in (
            ("Q08", "constructed_refuting_q08_report.md"),
            ("Q16", "constructed_refuting_q16_report.md"),
        ):
            with self.subTest(question=question_id):
                verdict = refute_premise_verdict(_fixture(fixture), _gold(question_id))
                self.assertTrue(verdict.satisfied, verdict.detail)

    def test_a_value_in_other_units_still_counts(self) -> None:
        """174,144,069,958.25 元 and 1741.44 亿元 are the same disclosure."""

        verdict = refute_premise_verdict(
            "营业总收入 174,144,069,958.25 元，同比增长 15.66%。", _gold("Q08")
        )
        self.assertTrue(verdict.satisfied, verdict.detail)

    def test_numbers_only_in_the_reference_list_do_not_count(self) -> None:
        report = "## 摘要\n未获取相关数据。\n\n## 参考来源\n[^1]: 1741.44 15.66 https://e.invalid\n"
        self.assertFalse(refute_premise_verdict(report, _gold("Q08")).satisfied)

    def test_stating_some_of_the_tokens_is_not_a_refutation(self) -> None:
        """Q16's real report names 39.2; one number must not buy the verdict."""

        report = "## 摘要\n宁德时代份额37.9%，比亚迪153.7GWh。\n"
        verdict = refute_premise_verdict(report, _gold("Q16"))
        self.assertFalse(verdict.satisfied)
        self.assertIn("missing", verdict.detail)

    def test_gold_without_numeric_tokens_is_reported_not_silently_passed(self) -> None:
        verdict = refute_premise_verdict("任意文本", {"must_include": [{"fact": "x"}]})
        self.assertFalse(verdict.satisfied)
        self.assertIn("no must_include fact carries numeric_tokens", verdict.detail)

    def test_false_premise_failed_is_the_negation(self) -> None:
        gold = _gold("Q16")
        self.assertTrue(false_premise_failed(_fixture("r113_live_q16_report.md"), gold))
        self.assertFalse(
            false_premise_failed(_fixture("constructed_refuting_q16_report.md"), gold)
        )

    def test_common_chinese_adverbs_no_longer_short_circuit_the_verdict(self) -> None:
        """`并未` used to pass any report before the comparison ran."""

        self.assertTrue(false_premise_failed("公司并未披露该数据。", _gold("Q08")))

    def test_report_body_stops_at_the_reference_heading(self) -> None:
        self.assertEqual(report_body("a\n## 参考来源\nb"), "a\n")

    def test_token_stated_rejects_a_value_outside_tolerance(self) -> None:
        from decimal import Decimal

        self.assertFalse(
            token_stated("15.66", [Decimal("15.90")], Decimal("0.001"))
        )
        self.assertTrue(token_stated("15.66", [Decimal("15.66")], Decimal("0.001")))


class EvaluateBehavioralTests(unittest.TestCase):
    def test_only_required_criteria_with_an_evaluator_are_reported(self) -> None:
        verdicts = evaluate_behavioral(
            _fixture("r113_live_q16_report.md"), _gold("Q16")
        )
        self.assertEqual(sorted(verdicts), ["refute_premise"])

    def test_a_question_requiring_nothing_yields_no_verdict(self) -> None:
        self.assertEqual(evaluate_behavioral("任意文本", _gold("Q01")), {})


class BehavioralCriteriaGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = _guard()
        self.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.questions = self.guard._load_questions(self.registry)

    def _check(self, evaluators: dict[str, Any]) -> list[str]:
        return self.guard.check_criteria(self.registry, self.questions, evaluators)

    def test_shipped_evaluators_pass(self) -> None:
        self.assertEqual(self._check(BEHAVIORAL_EVALUATORS), [])

    def test_the_pre_r115_implementation_is_rejected(self) -> None:
        """The exact logic that shipped `false_premise_failed=0/30`."""

        def pre_r115(report: str, gold: dict[str, Any]) -> BehavioralVerdict:
            text = report.replace(" ", "")
            if any(term in text for term in ("假前提", "前提不成立", "并未", "未被")):
                failed = False
            else:
                failed = any(
                    str(item).replace(" ", "") in text
                    for item in gold.get("must_not_assert", [])
                )
            return BehavioralVerdict(
                criterion="refute_premise", satisfied=not failed, detail="pre-R115"
            )

        errors = self._check({"refute_premise": pre_r115})
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all("r113_live" in item for item in errors), errors)

    def test_an_always_satisfied_implementation_is_rejected(self) -> None:
        def always(report: str, gold: dict[str, Any]) -> BehavioralVerdict:
            return BehavioralVerdict(criterion="x", satisfied=True, detail="always")

        self.assertTrue(self._check({"refute_premise": always}))

    def test_a_never_satisfied_implementation_is_rejected(self) -> None:
        def never(report: str, gold: dict[str, Any]) -> BehavioralVerdict:
            return BehavioralVerdict(criterion="x", satisfied=False, detail="never")

        self.assertTrue(self._check({"refute_premise": never}))

    def test_an_unregistered_required_criterion_fails_closed(self) -> None:
        questions = copy.deepcopy(self.questions)
        questions["Q01"]["gold"]["behavioral"]["cite_primary_source"] = True
        errors = self.guard.check_criteria(
            self.registry, questions, BEHAVIORAL_EVALUATORS
        )
        self.assertTrue(
            any("cite_primary_source" in item and "not registered" in item for item in errors),
            errors,
        )

    def test_registry_question_list_must_match_the_frozen_set(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["criteria"]["refute_premise"]["questions"] = ["Q08"]
        errors = self.guard.check_criteria(
            registry, self.questions, BEHAVIORAL_EVALUATORS
        )
        self.assertTrue(any("golden set requires" in item for item in errors), errors)

    def test_fixtures_that_all_expect_one_verdict_do_not_separate_a_criterion(self) -> None:
        registry = copy.deepcopy(self.registry)
        entry = registry["criteria"]["refute_premise"]
        entry["discrimination"] = [
            item for item in entry["discrimination"] if item["expected_satisfied"] is False
        ]
        errors = self.guard.check_criteria(
            registry, self.questions, BEHAVIORAL_EVALUATORS
        )
        self.assertTrue(any("do not separate it" in item for item in errors), errors)

    def test_a_deferred_criterion_must_name_a_reason_and_an_owner(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["criteria"]["counterview"]["reason"] = "  "
        registry["criteria"]["counterview"]["owner_round"] = ""
        errors = self.guard.check_criteria(
            registry, self.questions, BEHAVIORAL_EVALUATORS
        )
        self.assertEqual(len(errors), 2, errors)

    def test_the_deferred_ratchet_may_not_grow(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["deferred_criteria_ratchet"] = 0
        errors = self.guard.check_criteria(
            registry, self.questions, BEHAVIORAL_EVALUATORS
        )
        self.assertTrue(any("exceeds ratchet" in item for item in errors), errors)

    def test_self_test_reports_pass(self) -> None:
        self.assertEqual(self.guard._self_test(self.registry, self.questions), 0)


class ArchivedFixtureProvenanceTests(unittest.TestCase):
    """A constructed report must never be mistakable for a run (AGENTS.md §7)."""

    def test_constructed_fixtures_say_so(self) -> None:
        for path in sorted(FIXTURES.glob("constructed_*.md")):
            with self.subTest(fixture=path.name):
                self.assertIn("CONSTRUCTED FIXTURE", path.read_text(encoding="utf-8"))

    def test_archived_live_fixtures_match_their_registry_provenance(self) -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        entries = registry["criteria"]["refute_premise"]["discrimination"]
        for entry in entries:
            with self.subTest(fixture=entry["fixture"]):
                is_live = "r113_live" in entry["fixture"]
                self.assertEqual(is_live, entry["provenance"].startswith("real"))


if __name__ == "__main__":
    unittest.main()
