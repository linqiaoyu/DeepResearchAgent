"""Record the capabilities a run was assembled with.

R110 measured that 9 of 25 declared capabilities left no per-run evidence at
all, so an archived run could not answer "was the tool contract active?" or
"was rerank on?" without re-deriving the answer from configuration that is no
longer attached to it.

These nine differ from the rest in kind: they are decided when the run is
composed and have no unit of work to count. They are therefore recorded as
`composed` rather than `completed` -- the run states that the capability was
wired in, and claims nothing about what it did.
"""

from __future__ import annotations

from deepresearch_agent.observability.component_activity import (
    record_component_activity,
)
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings

#: `component name -> the settings attribute that decides it`. The names match
#: the flags so `check_capability_observability` can locate them by convention.
COMPOSITION_CAPABILITIES: tuple[tuple[str, str], ...] = (
    ("config_fail_fast", "config_fail_fast_enabled"),
    ("structured_logging", "structured_logging_enabled"),
    ("tool_contract", "tool_contract_enabled"),
    ("injection_guard", "injection_guard_enabled"),
    ("numeric_check", "numeric_check_enabled"),
    ("progressive_delivery", "progressive_delivery_enabled"),
    ("rerank", "rerank_enabled"),
    ("rerank_fail_open", "rerank_fail_open"),
    ("research_loop", "research_loop_active"),
)


def record_run_composition(state: ResearchState, settings: Settings) -> None:
    """State, once per run, which composition-time capabilities were wired in."""

    for component, attribute in COMPOSITION_CAPABILITIES:
        enabled = bool(getattr(settings, attribute))
        record_component_activity(
            state,
            component=component,
            enabled=enabled,
            status="composed" if enabled else "bypassed",
            inputs={"setting": attribute},
        )
