"""The domain with no opinion, used to exercise the harness without one."""

from __future__ import annotations

from deepresearch_agent.domains.base import BaseDomainPack


class NullDomainPack(BaseDomainPack):
    """Explicitly capability-empty pack for a generic offline workflow.

    Registered under `null` so the harness can be exercised, through the same
    registry an operator uses, with no domain opinion at all.
    """

    name = "null"
