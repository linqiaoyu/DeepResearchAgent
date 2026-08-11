"""LangGraph construction and entry routing."""

from __future__ import annotations

from deepresearch_agent.orchestration import GraphRuntime, RunScope, validate_contract_graph
from deepresearch_agent.skills import load_skills_if_enabled
from deepresearch_agent.workflow.contracts import build_workflow_contracts, workflow_contract_graph
from deepresearch_agent.workflow.state import ResearchGraphState
from langgraph.graph import END, START, StateGraph


class GraphAssembly:
    """Graph registration and initial skill-pack routing for the engine."""

    def _build_graph(self):
        self.node_contracts = build_workflow_contracts(
            self.settings,
            self.capability_registry,
        )
        validate_contract_graph(self.node_contracts, workflow_contract_graph())
        graph_runtime = GraphRuntime(self.node_contracts, self.logger)
        graph = StateGraph(ResearchGraphState, context_schema=RunScope)
        graph.add_node("entry", graph_runtime.wrap_node("entry", self._entry_node))
        graph.add_node("planner", graph_runtime.wrap_node("planner", self._planner_node))
        graph.add_node(
            "research_prepare",
            graph_runtime.wrap_node("research_prepare", self._research_prepare_node),
        )
        graph.add_node(
            "research_one",
            graph_runtime.wrap_node("research_one", self._research_one_node),
        )
        graph.add_node(
            "research_join",
            graph_runtime.wrap_node("research_join", self._research_join_node),
        )
        graph.add_node(
            "extractor",
            graph_runtime.wrap_node("extractor", self._extractor_node),
        )
        graph.add_node("critic", graph_runtime.wrap_node("critic", self._critic_node))
        graph.add_node(
            "reflector",
            graph_runtime.wrap_node("reflector", self._reflector_node),
        )
        graph.add_node(
            "research_loop_decide",
            graph_runtime.wrap_node(
                "research_loop_decide",
                self._research_loop_decide_node,
            ),
        )
        graph.add_node(
            "research_refine",
            graph_runtime.wrap_node("research_refine", self._research_refine_node),
        )
        graph.add_node(
            "retry_prepare",
            graph_runtime.wrap_node("retry_prepare", self._retry_prepare_node),
        )
        graph.add_node(
            "retry_one",
            graph_runtime.wrap_node("retry_one", self._retry_one_node),
        )
        graph.add_node(
            "retry_join",
            graph_runtime.wrap_node("retry_join", self._retry_join_node),
        )
        graph.add_node(
            "reporter",
            graph_runtime.wrap_node("reporter", self._reporter_node),
        )
        graph.add_node(
            "evaluator",
            graph_runtime.wrap_node("evaluator", self._evaluator_node),
        )

        graph.add_edge(START, "entry")
        graph.add_conditional_edges("entry", self._route_entry)
        graph.add_conditional_edges("planner", self._route_after_planning)
        graph.add_conditional_edges("research_prepare", self._send_research_tasks)
        graph.add_edge("research_one", "research_join")
        graph.add_conditional_edges("research_join", self._route_after_research)
        graph.add_conditional_edges("extractor", self._route_after_extraction)
        graph.add_conditional_edges("critic", self._route_after_critic)
        graph.add_conditional_edges(
            "research_loop_decide",
            self._route_after_research_loop,
        )
        graph.add_conditional_edges(
            "reflector",
            self._route_after_reflection,
        )
        graph.add_edge("research_refine", "research_prepare")
        graph.add_conditional_edges("retry_prepare", self._send_retry_tasks)
        graph.add_edge("retry_one", "retry_join")
        graph.add_edge("retry_join", "critic")
        graph.add_conditional_edges("reporter", self._route_after_reporting)
        graph.add_edge("evaluator", END)
        return graph.compile(checkpointer=self.checkpointer)

    def _entry_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not self.settings.skill_packs_enabled:
            state.metadata.setdefault(
                "skill_packs",
                {
                    "status": "bypassed",
                    "states": ["bypassed"],
                    "selection_complete": False,
                    "selected_skills": [],
                    "loaded_skills": [],
                    "registered_capabilities": [],
                },
            )
            result = dict(graph_state)
            result["research_state"] = self._dump_state(state)
            return result
        skill_metadata = state.metadata.get("skill_packs")
        if isinstance(skill_metadata, dict) and skill_metadata.get(
            "selection_complete"
        ):
            return graph_state
        try:
            outcome = load_skills_if_enabled(
                self.settings,
                self.skill_loader,
                state.topic,
                registry=self.capability_registry,
                state=state,
                is_applicable=self.domain_pack.metric_skill_applicable,
            )
        except Exception as exc:
            state.metadata["skill_packs"] = {
                "status": "failed",
                "states": ["failed"],
                "selection_complete": True,
                "selected_skills": [],
                "loaded_skills": [],
                "registered_capabilities": [],
                "failure": {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            state.metadata.setdefault("degradation_events", []).append(
                {
                    "tool": "skill_packs",
                    "reason": "load_failed",
                    "impact": "run continued without optional Skill resources",
                    "attempts": 1,
                }
            )
        else:
            loaded_skills = [
                {
                    "name": item.metadata.name,
                    "version": item.metadata.version,
                    "content_sha256": item.content_sha256,
                }
                for item in outcome.loaded_skills
            ]
            is_loaded = bool(loaded_skills)
            state.metadata["skill_packs"] = {
                "status": "loaded" if is_loaded else "bypassed",
                "states": (
                    ["selected", "loaded"] if is_loaded else ["bypassed"]
                ),
                "selection_complete": True,
                "selected_skills": list(outcome.selected_skills),
                "loaded_skills": loaded_skills,
                "registered_capabilities": list(
                    outcome.registered_capabilities
                ),
            }
        result = dict(graph_state)
        result["research_state"] = self._dump_state(state)
        return result

    def _route_entry(self, graph_state: ResearchGraphState) -> str:
        state = self._state_from_graph_values(graph_state)
        if state.status == "done" or state.current_phase == "done":
            return END
        return {
            "planning": "planner",
            "researching": "research_prepare",
            "extracting": "extractor",
            "critiquing": "critic",
            "reporting": "reporter",
            "evaluating": "evaluator",
        }[state.current_phase]
