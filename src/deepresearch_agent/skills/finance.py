from __future__ import annotations

from pathlib import Path

from deepresearch_agent.settings import project_root
from deepresearch_agent.skills.loader import SkillMetadata

FINANCE_METRIC_SKILL_NAME = "finance-metric-normalization"
FINANCE_METRIC_RESOURCE = "finance_metric_normalization.json"
_FINANCE_NUMERIC_TERMS = (
    "营收",
    "营业收入",
    "利润",
    "业绩",
    "毛利率",
    "净息差",
    "非息收入",
    "发电量",
    "装机量",
    "装车量",
    "出货量",
    "资本开支",
    "资本支出",
    "financial metric",
    "revenue",
    "profit",
    "margin",
    "capex",
)


def finance_metric_resource_path() -> Path:
    return (
        project_root()
        / "skills"
        / FINANCE_METRIC_SKILL_NAME
        / "resources"
        / FINANCE_METRIC_RESOURCE
    )


def finance_metric_skill_applicable(
    metadata: SkillMetadata,
    context: str,
) -> bool:
    if metadata.name != FINANCE_METRIC_SKILL_NAME:
        return False
    normalized = context.strip().lower()
    return any(term in normalized for term in _FINANCE_NUMERIC_TERMS)
