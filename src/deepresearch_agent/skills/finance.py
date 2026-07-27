"""Backward-compatible finance-skill API routed through the domain registry."""

from __future__ import annotations

from pathlib import Path

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.skills.loader import SkillMetadata


FINANCE_METRIC_SKILL_NAME = "finance-metric-normalization"
FINANCE_METRIC_RESOURCE = "finance_metric_normalization.json"


def finance_metric_resource_path() -> Path:
    return load_domain_pack("finance").metric_table_path()


def finance_metric_skill_applicable(metadata: SkillMetadata, context: str) -> bool:
    return load_domain_pack("finance").metric_skill_applicable(metadata, context)
