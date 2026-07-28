"""Fail-closed helpers for domain capabilities supplied at composition time."""

from __future__ import annotations

from typing import TypeVar

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.settings import load_settings


_DomainCapability = TypeVar("_DomainCapability")


def require_domain_capability(
    capability: _DomainCapability | None,
    *,
    consumer: str,
) -> _DomainCapability:
    """Require the composition root to supply a domain capability.

    Generic harness code must never silently substitute the finance pack.  A
    missing capability is an integration error, not a reason to change domain.
    """
    if capability is None:
        raise ValueError(
            f"{consumer} requires an explicitly injected domain capability; "
            "construct it through DeepResearchEngine or pass domain_pack=."
        )
    return capability


def legacy_configured_domain_capability(*, consumer: str) -> object:
    """Compatibility-only selection for standalone legacy constructors.

    The workflow composition root always injects a pack.  This preserves the
    public unit-level constructors while selecting the configured pack rather
    than naming or importing the finance implementation in a consumer.
    """
    del consumer
    return load_domain_pack(load_settings().domain_pack)


def resolve_domain_capability(
    capability: _DomainCapability | None,
    *,
    consumer: str,
) -> _DomainCapability:
    """Use explicit injection, retaining a configured legacy constructor path."""
    if capability is not None:
        return capability
    return legacy_configured_domain_capability(consumer=consumer)  # type: ignore[return-value]
