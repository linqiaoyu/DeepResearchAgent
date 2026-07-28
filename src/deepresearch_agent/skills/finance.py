"""Backward-compatible finance-skill API routed through the domain registry."""

from __future__ import annotations

from pathlib import Path

from deepresearch_agent.domains.protocols import ReportingDomain, SkillSelectionDomain
from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.skills.loader import SkillMetadata


FINANCE_METRIC_SKILL_NAME = "finance-metric-normalization"
FINANCE_METRIC_RESOURCE = "finance_metric_normalization.json"


def finance_metric_resource_path(domain_pack: ReportingDomain | None = None) -> Path:
    domain_pack = resolve_domain_capability(
        domain_pack, consumer="finance_metric_resource_path"
    )
    return domain_pack.metric_table_path()


def finance_metric_skill_applicable(
    metadata: SkillMetadata,
    context: str,
    domain_pack: SkillSelectionDomain | None = None,
) -> bool:
    domain_pack = resolve_domain_capability(
        domain_pack, consumer="finance_metric_skill_applicable"
    )
    return domain_pack.metric_skill_applicable(metadata, context)
