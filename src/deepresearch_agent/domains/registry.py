"""Resolve installed domain packs at the composition boundary."""

from __future__ import annotations

from deepresearch_agent.domains.protocols import DomainPack


def load_domain_pack(name: str) -> DomainPack:
    """Return a registered pack without exposing a concrete pack to callers."""
    if name == "finance":
        from deepresearch_agent.domains.finance import FinanceDomainPack

        return FinanceDomainPack()
    raise ValueError(f"unknown domain pack: {name!r}")
