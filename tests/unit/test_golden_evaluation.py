from __future__ import annotations

import unittest
import json

from deepresearch_agent.evaluation import (
    JudgeScore,
    aggregate_round_results,
    classify_bad_case,
    extract_report_claims,
    false_premise_failed,
    judge_sample_spread,
    validate_golden_design,
)
from deepresearch_agent.settings import project_root


def _valid_design() -> dict:
    types = ["财报解读"] * 8 + ["对比研究"] * 8 + ["行业研究"] * 7 + ["事件时间线"] * 7
    difficulties = ["易"] * 10 + ["中"] * 14 + ["难"] * 6
    questions = []
    for index, (question_type, difficulty) in enumerate(zip(types, difficulties, strict=True), 1):
        qid = f"Q{index:02d}"
        questions.append(
            {
                "id": qid,
                "type": question_type,
                "difficulty": difficulty,
                "companies": ["示例公司"],
                "topic": f"{qid} topic",
                "time_anchor": "2026-06-16",
                "trap_design": "none",
                "structured_data_required": False,
                "false_premise": qid in {"Q08", "Q16"},
                "gold": {
                    "must_include": ["required fact"],
                    "must_not_assert": [],
                    "behavioral": {"expected": "answer conservatively"},
                },
                "recording_notes": "record once with Tavily advanced search",
            }
        )
    return {"meta": {"pilot_set": ["Q01", "Q08", "Q09", "Q18", "Q26"]}, "questions": questions}


class GoldenEvaluationTests(unittest.TestCase):
    def test_validate_golden_design_accepts_locked_shape(self) -> None:
        self.assertEqual(validate_golden_design(_valid_design()), [])

    def test_validate_golden_design_reports_missing_required_fields(self) -> None:
        design = _valid_design()
        del design["questions"][0]["gold"]["must_include"]

        errors = validate_golden_design(design)

        self.assertIn("Q01 missing gold fields: ['must_include']", errors)
        self.assertIn("Q01 gold.must_include must be a non-empty list", errors)

    def test_validate_golden_design_locks_false_premise_ids(self) -> None:
        design = _valid_design()
        design["questions"][7]["false_premise"] = False

        errors = validate_golden_design(design)

        self.assertIn("false premise ids mismatch: ['Q16']", errors)

    def test_classify_bad_case_maps_score_and_flags(self) -> None:
        score = JudgeScore(
            fact_coverage=0.7,
            fact_accuracy=0.75,
            citation_support=0.9,
            synthesis_balance=0.79,
        )

        categories = classify_bad_case(
            score,
            citation_support_rate=0.5,
            false_premise_failed=True,
            temporal_issue=True,
            numeric_dimension_issue=True,
        )

        self.assertEqual(
            categories,
            [
                "检索不全",
                "事实错误",
                "口径标注错误",
                "引用不支持",
                "时间线错误",
                "假前提未识破",
                "结构或平衡缺失",
            ],
        )

    def test_judge_sample_spread_reports_dimension_ranges(self) -> None:
        samples = [
            JudgeScore(fact_coverage=0.9, fact_accuracy=0.8, citation_support=0.7, synthesis_balance=0.6),
            JudgeScore(fact_coverage=0.4, fact_accuracy=0.6, citation_support=0.7, synthesis_balance=0.9),
        ]

        self.assertEqual(
            judge_sample_spread(samples),
            {
                "fact_coverage": 0.5,
                "fact_accuracy": 0.2,
                "citation_support": 0.0,
                "synthesis_balance": 0.3,
            },
        )

    def test_extract_report_claims_skips_reference_section(self) -> None:
        claims = extract_report_claims(
            "\n".join(
                [
                    "# 标题",
                    "## 关键发现",
                    "- 2024年收入增长，并有来源[^1]。",
                    "- 短",
                    "## 参考来源",
                    "[^1]: source",
                ]
            )
        )

        self.assertEqual(claims, [{"claim": "2024年收入增长，并有来源。", "evidence_ids": ["1"]}])

    def test_aggregate_round_results_summarizes_scores_and_bad_cases(self) -> None:
        results = [
            {
                "status": "done",
                "judge": {
                    "median": {
                        "weighted_score": 0.8,
                        "fact_coverage": 0.7,
                        "fact_accuracy": 0.8,
                        "citation_support": 0.9,
                        "synthesis_balance": 1.0,
                    }
                },
                "citation_support": {"support_rate": 0.5},
                "mechanical": {"citation_resolution_rate": 0.75, "backfilled_citation_rate": 0.1},
                "cost_cny": 0.1,
                "latency_seconds": 1.5,
                "bad_case_categories": ["引用不支持"],
                "false_premise": True,
                "false_premise_failed": False,
            },
            {
                "status": "done",
                "judge": {
                    "median": {
                        "weighted_score": 0.6,
                        "fact_coverage": 0.5,
                        "fact_accuracy": 0.6,
                        "citation_support": 0.7,
                        "synthesis_balance": 0.8,
                    }
                },
                "citation_support": {"support_rate": 1.0},
                "mechanical": {"citation_resolution_rate": 0.25, "backfilled_citation_rate": 0.3},
                "cost_cny": 0.2,
                "latency_seconds": 2.5,
                "bad_case_categories": ["引用不支持", "事实错误"],
            },
        ]

        summary = aggregate_round_results(results)

        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["avg_weighted_score"], 0.7)
        self.assertEqual(summary["avg_citation_support_rate"], 0.75)
        self.assertEqual(summary["avg_backfilled_citation_rate"], 0.2)
        self.assertEqual(summary["bad_case_categories"], {"引用不支持": 2, "事实错误": 1})
        self.assertEqual(summary["false_premise"], {"passed": 1, "failed": 0})

    def test_false_premise_failed_honors_explicit_refutation(self) -> None:
        self.assertFalse(false_premise_failed("题目前提不成立：并未下滑。", ["下滑原因"]))
        self.assertTrue(false_premise_failed("以下分析下滑原因。", ["下滑原因"]))

    def test_frozen_golden_set_v1_asset_has_locked_shape(self) -> None:
        path = project_root() / "data" / "golden_set" / "v1" / "questions.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["meta"]["version"], "v1.0")
        self.assertLessEqual(payload["meta"]["quarantine_count"], 3)
        self.assertEqual(validate_golden_design(payload), [])
        self.assertEqual(len(payload["questions"]), 30)
        self.assertTrue(
            all(
                "source_ref" in item
                for question in payload["questions"]
                for item in question["gold"]["must_include"]
            )
        )


if __name__ == "__main__":
    unittest.main()
