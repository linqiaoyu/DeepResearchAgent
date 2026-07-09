from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from deepresearch_agent.evaluation.judge import JudgeScore

EXPECTED_TYPE_DISTRIBUTION = {"财报解读": 8, "对比研究": 8, "行业研究": 7, "事件时间线": 7}
EXPECTED_DIFFICULTY_DISTRIBUTION = {"易": 10, "中": 14, "难": 6}
EXPECTED_FALSE_PREMISE_IDS = ["Q08", "Q16"]
REQUIRED_QUESTION_FIELDS = {
    "type",
    "difficulty",
    "companies",
    "topic",
    "time_anchor",
    "trap_design",
    "structured_data_required",
    "gold",
    "recording_notes",
}
REQUIRED_GOLD_FIELDS = {"must_include", "must_not_assert", "behavioral"}
JUDGE_DIMENSIONS = ("fact_coverage", "fact_accuracy", "citation_support", "synthesis_balance")


def load_yaml_design(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate_golden_design(design: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    questions = design.get("questions")
    if not isinstance(questions, list):
        return ["questions must be a list"]

    ids = [item.get("id") if isinstance(item, dict) else None for item in questions]
    expected_ids = [f"Q{index:02d}" for index in range(1, 31)]
    if ids != expected_ids:
        errors.append("question ids must be exactly Q01..Q30 in order")
    if len(set(ids)) != len(ids):
        errors.append("question ids must be unique")

    type_counts = Counter()
    difficulty_counts = Counter()
    false_premise_ids: list[str] = []
    for index, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            errors.append(f"question #{index} must be a mapping")
            continue
        qid = str(question.get("id", f"#{index}"))
        missing = sorted(REQUIRED_QUESTION_FIELDS - set(question))
        if missing:
            errors.append(f"{qid} missing question fields: {missing}")
        type_counts.update([question.get("type")])
        difficulty_counts.update([question.get("difficulty")])
        if question.get("false_premise") is True:
            false_premise_ids.append(qid)
        gold = question.get("gold")
        if not isinstance(gold, dict):
            errors.append(f"{qid} gold must be a mapping")
            continue
        missing_gold = sorted(REQUIRED_GOLD_FIELDS - set(gold))
        if missing_gold:
            errors.append(f"{qid} missing gold fields: {missing_gold}")
        if not isinstance(gold.get("must_include"), list) or not gold.get("must_include"):
            errors.append(f"{qid} gold.must_include must be a non-empty list")
        if not isinstance(gold.get("must_not_assert"), list):
            errors.append(f"{qid} gold.must_not_assert must be a list")
        if not isinstance(gold.get("behavioral"), dict):
            errors.append(f"{qid} gold.behavioral must be a mapping")

    if dict(type_counts) != EXPECTED_TYPE_DISTRIBUTION:
        errors.append(f"type distribution mismatch: {json.dumps(dict(type_counts), ensure_ascii=False)}")
    if dict(difficulty_counts) != EXPECTED_DIFFICULTY_DISTRIBUTION:
        errors.append(
            f"difficulty distribution mismatch: {json.dumps(dict(difficulty_counts), ensure_ascii=False)}"
        )
    if false_premise_ids != EXPECTED_FALSE_PREMISE_IDS:
        errors.append(f"false premise ids mismatch: {false_premise_ids}")

    pilot_set = design.get("meta", {}).get("pilot_set", [])
    if len(pilot_set) != 5 or not all(qid in ids for qid in pilot_set):
        errors.append(f"pilot_set must contain five existing question ids: {pilot_set}")
    return errors


def classify_bad_case(
    score: JudgeScore,
    citation_support_rate: float,
    *,
    false_premise_failed: bool = False,
    temporal_issue: bool = False,
    numeric_dimension_issue: bool = False,
) -> list[str]:
    categories: list[str] = []
    if score.fact_coverage < 0.8:
        categories.append("检索不全")
    if score.fact_accuracy < 0.8:
        categories.append("事实错误")
    if numeric_dimension_issue:
        categories.append("口径标注错误")
    if citation_support_rate < 0.8 or score.citation_support < 0.8:
        categories.append("引用不支持")
    if temporal_issue:
        categories.append("时间线错误")
    if false_premise_failed:
        categories.append("假前提未识破")
    if score.synthesis_balance < 0.8:
        categories.append("结构或平衡缺失")
    return categories


def judge_sample_spread(samples: list[JudgeScore]) -> dict[str, float]:
    if not samples:
        return {key: 0.0 for key in JUDGE_DIMENSIONS}
    return {
        key: round(max(getattr(item, key) for item in samples) - min(getattr(item, key) for item in samples), 4)
        for key in JUDGE_DIMENSIONS
    }


def extract_report_claims(report: str, *, limit: int = 12) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    reference_section = False
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## 参考来源"):
            reference_section = True
            continue
        if reference_section:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            claim_text = stripped[2:].strip()
        elif stripped.startswith(("比", "据", "202", "报告", "公司", "行业", "宁", "贵", "美", "中")):
            claim_text = stripped
        else:
            continue
        if len(claim_text) < 10:
            continue
        evidence_ids = re.findall(r"\[\^([^\]]+)\]", claim_text)
        claims.append(
            {
                "claim": re.sub(r"\[\^[^\]]+\]", "", claim_text).strip(),
                "evidence_ids": evidence_ids,
            }
        )
        if len(claims) >= limit:
            break
    return claims


def aggregate_round_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in results if item.get("status") == "done"]
    if not completed:
        return {"cases": 0}

    def _avg(path: tuple[str, ...]) -> float:
        values: list[float] = []
        for item in completed:
            current: Any = item
            for key in path:
                current = current.get(key, {}) if isinstance(current, dict) else {}
            if isinstance(current, int | float):
                values.append(float(current))
        return round(sum(values) / len(values), 4) if values else 0.0

    category_counts = Counter()
    false_premise = {"passed": 0, "failed": 0}
    for item in completed:
        category_counts.update(item.get("bad_case_categories", []))
        if item.get("false_premise") is True:
            if item.get("false_premise_failed") is True:
                false_premise["failed"] += 1
            else:
                false_premise["passed"] += 1

    return {
        "cases": len(completed),
        "avg_weighted_score": _avg(("judge", "median", "weighted_score")),
        "avg_fact_coverage": _avg(("judge", "median", "fact_coverage")),
        "avg_fact_accuracy": _avg(("judge", "median", "fact_accuracy")),
        "avg_citation_support": _avg(("judge", "median", "citation_support")),
        "avg_synthesis_balance": _avg(("judge", "median", "synthesis_balance")),
        "avg_citation_support_rate": _avg(("citation_support", "support_rate")),
        "avg_citation_resolution_rate": _avg(("mechanical", "citation_resolution_rate")),
        "avg_citation_repair_retry_rate": _avg(("mechanical", "citation_repair_retry_rate")),
        "avg_uncited_claim_rate": _avg(("mechanical", "uncited_claim_rate")),
        "total_cost_cny": round(sum(float(item.get("cost_cny", 0.0)) for item in completed), 6),
        "total_latency_seconds": round(
            sum(float(item.get("latency_seconds", 0.0)) for item in completed), 3
        ),
        "bad_case_categories": dict(category_counts),
        "false_premise": false_premise,
    }


def false_premise_failed(report: str, must_not_assert: list[str]) -> bool:
    text = report.replace(" ", "")
    if "假前提" in text or "前提不成立" in text or "并未" in text or "未被" in text:
        return False
    return any(item.replace(" ", "") in text for item in must_not_assert)
