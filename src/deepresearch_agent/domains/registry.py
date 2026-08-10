"""Resolve installed domain packs at the composition boundary."""

from __future__ import annotations

from collections.abc import Callable

from deepresearch_agent.domains.protocols import DomainPack


def _finance() -> DomainPack:
    from deepresearch_agent.domains.finance import FinanceDomainPack

    pack: DomainPack = FinanceDomainPack()
    return pack


def _null() -> DomainPack:
    from deepresearch_agent.domains.null import NullDomainPack

    pack: DomainPack = NullDomainPack()
    return pack


#: R110: this registry knew exactly one name, so `DEEPRESEARCH_DOMAIN_PACK`
#: could only ever be `finance` and any other value killed the process at
#: startup. `NullDomainPack` already existed as the harness's own composition
#: fixture -- 234 lines proving the workflow runs with no metric vocabulary, no
#: disclosure policy and no numeric interpretation -- but was reachable only by
#: injecting it inside a test. A registry with one entry cannot support the
#: claim that a domain is swappable without touching the core, so the fixture
#: pack is registered and the swap is exercised through the same path an
#: operator would use.
#:
#: `null` is deliberately not a product domain. It is here to keep the harness
#: honest about what it does without one.
_PACKS: dict[str, Callable[[], DomainPack]] = {
    "finance": _finance,
    "null": _null,
}


def installed_domain_packs() -> tuple[str, ...]:
    """Names `DEEPRESEARCH_DOMAIN_PACK` accepts."""

    return tuple(sorted(_PACKS))


def load_domain_pack(name: str) -> DomainPack:
    """Return a registered pack without exposing a concrete pack to callers."""

    build = _PACKS.get(name)
    if build is None:
        raise ValueError(
            f"unknown domain pack: {name!r}; installed: {installed_domain_packs()}"
        )
    return build()
