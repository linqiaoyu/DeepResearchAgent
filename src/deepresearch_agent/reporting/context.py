from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from deepresearch_agent.memory import (
    ContextWorkingMemory,
    WorkingMemoryQuery,
    WorkingMemoryWrite,
)
from deepresearch_agent.observability import record_component_activity
from deepresearch_agent.schemas import Evidence, ResearchState


@dataclass(frozen=True)
class ReporterContext:
    """A bounded generation view that never replaces canonical Evidence."""

    evidence: tuple[Evidence, ...]
    packed: bool


class ReporterContextBuilder:
    """Build the LLM prompt view while preserving the research state contract."""

    def __init__(self, working_memory: ContextWorkingMemory) -> None:
        self.working_memory = working_memory

    def build(
        self,
        state: ResearchState,
        *,
        enabled: bool,
        budget: int,
        as_of: date | None,
    ) -> ReporterContext:
        canonical = tuple(state.evidence_store)
        if not enabled:
            record_component_activity(
                state,
                component="working_memory",
                enabled=False,
                status="bypassed",
                inputs={"evidence_before": len(canonical)},
                outputs={
                    "selected": len(canonical),
                    "dropped": 0,
                    "canonical_evidence_preserved": True,
                },
            )
            return ReporterContext(evidence=canonical, packed=False)

        self.working_memory.write(
            WorkingMemoryWrite(
                research_id=state.research_id,
                evidence=list(canonical),
                as_of=as_of or date.today(),
                provenance_refs=tuple(
                    sorted(
                        {
                            item.source_url
                            for item in canonical
                            if item.source_url
                        }
                    )
                ) or (f"run:{state.research_id}",),
            )
        )
        packed = self.working_memory.query(
            WorkingMemoryQuery(
                research_id=state.research_id,
                topic=state.topic,
                budget=budget,
                as_of=as_of,
            )
        )
        state.metadata.setdefault("context_events", []).append(
            packed.context_event(node="reporter")
        )
        record_component_activity(
            state,
            component="working_memory",
            enabled=True,
            status="completed",
            inputs={"evidence_before": len(canonical)},
            outputs={
                "selected": len(packed.selected),
                "dropped": len(packed.dropped),
                "canonical_evidence_preserved": True,
            },
        )
        return ReporterContext(
            evidence=tuple(packed.selected),
            packed=True,
        )
