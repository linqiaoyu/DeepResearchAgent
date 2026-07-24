from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.schemas import AgentDecision, ResearchState
from langgraph.graph import END, START, StateGraph

ProgressMetric = Callable[[ResearchState], float]
ExhaustedHandler = Callable[[ResearchState, str], None]


@dataclass(frozen=True)
class LoopSpec:
    """Reusable contract for a bounded LangGraph conditional loop."""

    max_iterations: int
    budget_ceiling: int
    no_progress_window: int
    progress_metric: ProgressMetric
    on_exhausted: ExhaustedHandler
    budget_unit: Literal["calls", "tokens"] = "calls"
    min_progress_delta: float = 0.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if self.budget_ceiling < 0:
            raise ValueError("budget_ceiling must be non-negative")
        if self.no_progress_window < 1:
            raise ValueError("no_progress_window must be at least 1")
        if self.min_progress_delta < 0:
            raise ValueError("min_progress_delta must be non-negative")


@dataclass(frozen=True)
class LoopContext:
    iteration: int
    remaining_budget: int
    budget_unit: Literal["calls", "tokens"]


@dataclass(frozen=True)
class LoopIterationResult:
    """Accounting returned by one injected research strategy iteration."""

    budget_consumed: int
    retry_budget_consumed: int = 0
    stop_requested: bool = False
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        if self.budget_consumed < 0:
            raise ValueError("budget_consumed must be non-negative")
        if self.retry_budget_consumed < 0:
            raise ValueError("retry_budget_consumed must be non-negative")


LoopStep = Callable[[ResearchState, LoopContext], LoopIterationResult]


@dataclass(frozen=True)
class LoopTracker:
    iteration: int
    budget_used: int
    best_metric: float
    last_metric: float
    no_progress_count: int


@dataclass(frozen=True)
class LoopOutcome:
    tracker: LoopTracker
    route: Literal["continue", "stop"]
    stop_boundary: str | None
    outcome: str


class _LoopGraphState(TypedDict):
    research_state: ResearchState
    iteration: int
    budget_used: int
    best_metric: float
    metric_before: float
    last_metric: float
    no_progress_count: int
    last_result: LoopIterationResult | None
    route: Literal["continue", "stop"]
    stop_boundary: str | None


class BoundedLoop:
    """Execute an injected strategy through a native LangGraph conditional edge."""

    def __init__(self, spec: LoopSpec, step: LoopStep) -> None:
        self.spec = spec
        self.step = step
        graph = StateGraph(_LoopGraphState)
        graph.add_node("loop_iteration", self._iteration_node)
        graph.add_node("loop_decide", self._decision_node)
        graph.add_edge(START, "loop_iteration")
        graph.add_edge("loop_iteration", "loop_decide")
        # This is the project's first reusable native LangGraph back-edge.
        # LangGraph remains the executor; BoundedLoop only supplies bounded state
        # and the conditional route.
        graph.add_conditional_edges(
            "loop_decide",
            self._route,
            {
                "continue": "loop_iteration",
                "stop": END,
            },
        )
        self.graph = graph.compile()

    def run(self, state: ResearchState) -> ResearchState:
        tracker = self.start(state)
        initial: _LoopGraphState = {
            "research_state": state,
            "iteration": tracker.iteration,
            "budget_used": tracker.budget_used,
            "best_metric": tracker.best_metric,
            "metric_before": tracker.last_metric,
            "last_metric": tracker.last_metric,
            "no_progress_count": tracker.no_progress_count,
            "last_result": None,
            "route": "continue",
            "stop_boundary": None,
        }
        if self.spec.budget_ceiling == 0:
            self._exhaust(state, "budget_ceiling")
            return state
        result = self.graph.invoke(
            initial,
            config={
                "recursion_limit": max(
                    25,
                    self.spec.max_iterations * 3 + 5,
                )
            },
        )
        return result["research_state"]

    def start(self, state: ResearchState) -> LoopTracker:
        initial_metric = float(self.spec.progress_metric(state))
        return LoopTracker(
            iteration=0,
            budget_used=0,
            best_metric=initial_metric,
            last_metric=initial_metric,
            no_progress_count=0,
        )

    def advance(
        self,
        state: ResearchState,
        tracker: LoopTracker,
        result: LoopIterationResult,
    ) -> LoopOutcome:
        remaining = self.spec.budget_ceiling - tracker.budget_used
        if result.budget_consumed > remaining:
            raise ValueError(
                "loop step exceeded remaining budget: "
                f"consumed={result.budget_consumed}, remaining={remaining}"
            )
        metric = float(self.spec.progress_metric(state))
        improved = metric > (
            tracker.best_metric + self.spec.min_progress_delta
        )
        advanced = LoopTracker(
            iteration=tracker.iteration + 1,
            budget_used=tracker.budget_used + result.budget_consumed,
            best_metric=metric if improved else tracker.best_metric,
            last_metric=metric,
            no_progress_count=(
                0 if improved else tracker.no_progress_count + 1
            ),
        )
        route, stop_boundary, outcome = self._evaluate_outcome(
            advanced,
            result,
        )
        self._record_decision(
            state,
            advanced,
            result,
            metric_before=tracker.last_metric,
            route=route,
            stop_boundary=stop_boundary,
            outcome=outcome,
        )
        if stop_boundary:
            self._exhaust(state, stop_boundary)
        return LoopOutcome(
            tracker=advanced,
            route=route,
            stop_boundary=stop_boundary,
            outcome=outcome,
        )

    def _iteration_node(self, graph_state: _LoopGraphState) -> dict[str, object]:
        iteration = graph_state["iteration"] + 1
        remaining = self.spec.budget_ceiling - graph_state["budget_used"]
        context = LoopContext(
            iteration=iteration,
            remaining_budget=remaining,
            budget_unit=self.spec.budget_unit,
        )
        result = self.step(graph_state["research_state"], context)
        if result.budget_consumed > remaining:
            raise ValueError(
                "loop step exceeded remaining budget: "
                f"consumed={result.budget_consumed}, remaining={remaining}"
            )
        metric = float(self.spec.progress_metric(graph_state["research_state"]))
        improved = metric > (
            graph_state["best_metric"] + self.spec.min_progress_delta
        )
        return {
            "iteration": iteration,
            "budget_used": (
                graph_state["budget_used"] + result.budget_consumed
            ),
            "best_metric": (
                metric if improved else graph_state["best_metric"]
            ),
            "metric_before": graph_state["last_metric"],
            "last_metric": metric,
            "no_progress_count": (
                0 if improved else graph_state["no_progress_count"] + 1
            ),
            "last_result": result,
        }

    def _decision_node(self, graph_state: _LoopGraphState) -> dict[str, object]:
        result = graph_state["last_result"]
        if result is None:
            raise RuntimeError("loop_decide requires one completed iteration")
        tracker = LoopTracker(
            iteration=graph_state["iteration"],
            budget_used=graph_state["budget_used"],
            best_metric=graph_state["best_metric"],
            last_metric=graph_state["last_metric"],
            no_progress_count=graph_state["no_progress_count"],
        )
        route, stop_boundary, outcome = self._evaluate_outcome(
            tracker,
            result,
        )
        self._record_decision(
            graph_state["research_state"],
            tracker,
            result,
            metric_before=graph_state["metric_before"],
            route=route,
            stop_boundary=stop_boundary,
            outcome=outcome,
        )
        if stop_boundary:
            self._exhaust(graph_state["research_state"], stop_boundary)
        return {
            "route": route,
            "stop_boundary": stop_boundary,
        }

    def _evaluate_outcome(
        self,
        tracker: LoopTracker,
        result: LoopIterationResult,
    ) -> tuple[Literal["continue", "stop"], str | None, str]:
        boundaries: list[str] = []
        if tracker.budget_used >= self.spec.budget_ceiling:
            boundaries.append("budget_ceiling")
        if tracker.iteration >= self.spec.max_iterations:
            boundaries.append("max_iterations")
        if tracker.no_progress_count >= self.spec.no_progress_window:
            boundaries.append("no_progress_window")

        if boundaries:
            route: Literal["continue", "stop"] = "stop"
            stop_boundary = "+".join(boundaries)
            outcome = f"stop_exhausted:{stop_boundary}"
        elif result.stop_requested:
            route = "stop"
            stop_boundary = None
            outcome = f"stop_sufficient:{result.stop_reason or 'strategy_requested'}"
        else:
            route = "continue"
            stop_boundary = None
            outcome = "continue"

        return route, stop_boundary, outcome

    def _record_decision(
        self,
        state: ResearchState,
        tracker: LoopTracker,
        result: LoopIterationResult,
        *,
        metric_before: float,
        route: Literal["continue", "stop"],
        stop_boundary: str | None,
        outcome: str,
    ) -> None:
        boundaries = stop_boundary.split("+") if stop_boundary else []
        decision = AgentDecision(
            decision_type="bounded_loop_control",
            made_by="BoundedLoop",
            inputs={
                "metric_before": metric_before,
                "metric_after": tracker.last_metric,
                "budget_used": tracker.budget_used,
                "budget_ceiling": self.spec.budget_ceiling,
                "budget_unit": self.spec.budget_unit,
                "retry_budget_consumed": result.retry_budget_consumed,
                "iteration": tracker.iteration,
                "max_iterations": self.spec.max_iterations,
                "no_progress_count": tracker.no_progress_count,
                "no_progress_window": self.spec.no_progress_window,
                "boundaries_triggered": boundaries,
                "route": route,
            },
            criterion=(
                "stop when the strategy reports sufficiency or any of "
                "max_iterations, budget_ceiling, no_progress_window is reached"
            ),
            outcome=outcome,
            alternatives_considered=[
                "continue",
                "stop_sufficient",
                "stop_and_mark_coverage_insufficient",
            ],
            iteration=tracker.iteration,
        )
        record_agent_decision(state, decision)

    def _route(
        self,
        graph_state: _LoopGraphState,
    ) -> Literal["continue", "stop"]:
        return graph_state["route"]

    def _exhaust(self, state: ResearchState, boundary: str) -> None:
        notice = f"因 {boundary} 边界停止，覆盖可能不足。"
        loop_metadata = state.metadata.setdefault("research_loop", {})
        loop_metadata["stop_boundary"] = boundary
        loop_metadata["coverage_warning"] = notice
        warnings = state.metadata.setdefault("coverage_warnings", [])
        if notice not in warnings:
            warnings.append(notice)
        for attribute in ("final_report", "draft_report"):
            report = getattr(state, attribute)
            if report and notice not in report:
                setattr(
                    state,
                    attribute,
                    f"{report}\n\n## 研究覆盖提示\n\n{notice}",
                )
        self.spec.on_exhausted(state, boundary)
