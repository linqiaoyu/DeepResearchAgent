from __future__ import annotations

from typing import Any

from deepresearch_agent.orchestration import (
    ContractField,
    ContractGraph,
    ContractInvariant,
    NodeContract,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import CapabilityRegistry


def workflow_contract_graph() -> ContractGraph:
    return ContractGraph(
        edges=(
            ("entry", "planner"), ("entry", "research_prepare"),
            ("entry", "extractor"), ("entry", "critic"),
            ("entry", "reporter"), ("entry", "evaluator"),
            ("planner", "research_prepare"),
            ("research_prepare", "research_one"),
            ("research_prepare", "research_join"),
            ("research_one", "research_join"), ("research_join", "extractor"),
            ("extractor", "critic"), ("critic", "retry_prepare"),
            ("critic", "reporter"), ("critic", "research_loop_decide"),
            ("critic", "reflector"), ("research_loop_decide", "reporter"),
            ("research_loop_decide", "research_refine"),
            ("research_loop_decide", "reflector"), ("reflector", "reporter"),
            ("reflector", "research_refine"),
            ("research_refine", "research_prepare"),
            ("retry_prepare", "retry_one"), ("retry_prepare", "retry_join"),
            ("retry_one", "retry_join"), ("retry_join", "critic"),
            ("reporter", "evaluator"),
        ),
        injected_paths=frozenset(
            {"research_state", "fanout_sub_question", "fanout_retry_task"}
        ),
    )


def build_workflow_contracts(
    settings: Settings,
    capability_registry: CapabilityRegistry,
) -> dict[str, NodeContract]:
    state_field = ContractField(dict)
    optional_dict = ContractField(dict, required=False)
    identity = ContractInvariant(
        name="research_identity_preserved",
        predicate=research_identity_preserved,
        expectation="research_id and topic remain unchanged across the node",
    )
    selected_capabilities = ContractInvariant(
        name="selected_capabilities_registered",
        predicate=lambda before, after: selected_capabilities_registered(
            before, after, capability_registry
        ),
        expectation="every selected capability resolves from CapabilityRegistry",
    )
    numeric_issues = ContractInvariant(
        name="numeric_issues_complete",
        predicate=numeric_issues_complete,
        expectation=(
            "every numeric_inconsistency carries claimed_value, calculated_value, "
            "formula, and evidence_ids"
        ),
    )
    footnotes = ContractInvariant(
        name="footnotes_reference_known_evidence",
        predicate=footnotes_reference_known_evidence,
        expectation="every report footnote maps to an evidence id in research_state.evidence_store",
    )
    return {
        "entry": NodeContract(name="entry", consumes={"research_state": state_field}, produces=frozenset({"research_state"}), invariants=(identity,)),
        "planner": NodeContract(name="planner", consumes={"research_state": state_field}, produces=frozenset({"research_state.plan", "research_state.todo_list", "research_state.pending_tasks", "research_state.current_phase"}), invariants=(identity,)),
        "research_prepare": NodeContract(
            name="research_prepare",
            consumes={"research_state": state_field, "research_state.plan": ContractField(dict)},
            produces=frozenset({"research_state", "active_sub_question_ids"} | ({"research_state.agent_decisions"} if settings.dynamic_capability_enabled else set())),
            invariants=(identity, *((selected_capabilities,) if settings.dynamic_capability_enabled else ())),
            decision_node=settings.dynamic_capability_enabled,
        ),
        "research_one": NodeContract(name="research_one", consumes={"research_state": state_field, "fanout_sub_question": ContractField(dict)}, produces=frozenset({"research_sources", "research_records", "research_structured_evidence", "research_structured_stats", "research_symbol_resolutions", "research_decisions"}), invariants=(identity,)),
        "research_join": NodeContract(
            name="research_join",
            consumes={"research_state": state_field, "research_state.plan": ContractField(dict), "research_sources": optional_dict, "research_records": optional_dict, "research_structured_evidence": optional_dict, "research_structured_stats": optional_dict, "research_symbol_resolutions": optional_dict, "research_decisions": optional_dict},
            produces=frozenset({"research_state.sources", "research_state.search_records", "research_state.evidence_store", "research_state.current_phase", *({"research_state.agent_decisions"} if settings.dynamic_capability_enabled else set())}),
            invariants=(identity,), decision_node=settings.dynamic_capability_enabled,
        ),
        "extractor": NodeContract(name="extractor", consumes={"research_state": state_field, "research_state.plan": ContractField(dict), "research_state.sources": ContractField(list)}, produces=frozenset({"research_state.evidence_store", "research_state.current_phase"}), invariants=(identity,)),
        "critic": NodeContract(
            name="critic",
            consumes={"research_state": state_field, "research_state.plan": ContractField(dict), "research_state.evidence_store": ContractField(list)},
            produces=frozenset({"research_state.critic_report", "research_state.retry_queue", "research_state.current_phase"} | ({"research_state.agent_decisions"} if settings.numeric_check_enabled else set())),
            invariants=(
                identity,
                *(
                    (numeric_issues,)
                    if settings.numeric_check_enabled and settings.critic_enabled
                    else ()
                ),
            ),
            decision_node=(
                settings.numeric_check_enabled and settings.critic_enabled
            ),
        ),
        "reflector": NodeContract(name="reflector", consumes={"research_state": state_field, "research_state.agent_decisions": ContractField(list)}, produces=frozenset({"research_state.metadata.reflection_result", "research_state.agent_decisions"}), invariants=(identity,), decision_node=settings.reflection_enabled),
        "research_loop_decide": NodeContract(name="research_loop_decide", consumes={"research_state": state_field, "research_state.plan": ContractField(dict), "research_state.evidence_store": ContractField(list), "research_state.critic_report": ContractField(dict)}, produces=frozenset({"research_state.metadata", "research_state.agent_decisions"}), invariants=(identity,), decision_node=True),
        "research_refine": NodeContract(name="research_refine", consumes={"research_state": state_field, "research_state.plan": ContractField(dict)}, produces=frozenset({"research_state.plan", "research_state.agent_decisions"}), invariants=(identity,), decision_node=True),
        "retry_prepare": NodeContract(name="retry_prepare", consumes={"research_state": state_field, "research_state.retry_queue": ContractField(list)}, produces=frozenset({"research_state", "active_retry_task_ids"}), invariants=(identity,)),
        "retry_one": NodeContract(name="retry_one", consumes={"research_state": state_field, "fanout_retry_task": ContractField(dict)}, produces=frozenset({"retry_sources", "retry_records"}), invariants=(identity,)),
        "retry_join": NodeContract(name="retry_join", consumes={"research_state": state_field, "research_state.retry_queue": ContractField(list), "retry_sources": optional_dict, "retry_records": optional_dict}, produces=frozenset({"research_state.evidence_store", "research_state.retry_queue", "research_state.current_phase"}), invariants=(identity,)),
        "reporter": NodeContract(name="reporter", consumes={"research_state": state_field, "research_state.plan": ContractField(dict), "research_state.evidence_store": ContractField(list)}, produces=frozenset({"research_state.final_report", "research_state.draft_report", "research_state.report_footnote_evidence", "research_state.report_evidence_selections", "research_state.current_phase"}), invariants=(identity, footnotes)),
        "evaluator": NodeContract(name="evaluator", consumes={"research_state": state_field, "research_state.final_report": ContractField(str), "research_state.evidence_store": ContractField(list), "research_state.report_footnote_evidence": ContractField(dict)}, produces=frozenset({"research_state.evaluation", "research_state.current_phase", "research_state.status"}), invariants=(identity,)),
    }


def research_identity_preserved(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_state = before.get("research_state")
    after_state = after.get("research_state")
    return isinstance(before_state, dict) and isinstance(after_state, dict) and (
        before_state.get("research_id") == after_state.get("research_id")
        and before_state.get("topic") == after_state.get("topic")
    )


def footnotes_reference_known_evidence(_before: dict[str, Any], after: dict[str, Any]) -> bool:
    state = after.get("research_state")
    if not isinstance(state, dict):
        return False
    evidence_ids = {item.get("id") for item in state.get("evidence_store", []) if isinstance(item, dict)}
    mapping = state.get("report_footnote_evidence")
    return isinstance(mapping, dict) and set(mapping.values()).issubset(evidence_ids)


def numeric_issues_complete(_before: dict[str, Any], after: dict[str, Any]) -> bool:
    state = after.get("research_state")
    if not isinstance(state, dict):
        return False
    report = state.get("critic_report")
    # A disabled Critic deliberately emits no report and therefore cannot
    # contain an incomplete numeric issue.  The caller only attaches this
    # invariant when Critic is enabled; accepting the absent value also keeps
    # the predicate total for paused/short-circuited graph states.
    if not isinstance(report, dict):
        return True
    return all(
        issue.get("claimed_value") is not None
        and issue.get("calculated_value") is not None
        and bool(issue.get("formula"))
        and bool(issue.get("evidence_ids"))
        for issue in report.get("issues", [])
        if isinstance(issue, dict) and issue.get("issue_type") == "numeric_inconsistency"
    )


def selected_capabilities_registered(
    _before: dict[str, Any], after: dict[str, Any], registry: CapabilityRegistry
) -> bool:
    state = after.get("research_state")
    if not isinstance(state, dict):
        return False
    metadata = state.get("metadata", {})
    selections = metadata.get("capability_selections", {}) if isinstance(metadata, dict) else {}
    if not isinstance(selections, dict) or not selections:
        return False
    registered = {item.name for item in registry.query()}
    return all(
        isinstance(selection, dict)
        and bool(selection.get("selected_capabilities"))
        and set(selection.get("selected_capabilities", [])).issubset(registered)
        for selection in selections.values()
    )
