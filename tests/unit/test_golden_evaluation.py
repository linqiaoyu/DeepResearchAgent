from __future__ import annotations

import unittest

from deepresearch_agent.evaluation import JudgeScore, classify_bad_case, validate_golden_design


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


if __name__ == "__main__":
    unittest.main()
