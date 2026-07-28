from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from deepresearch_agent.security.content import redact
from deepresearch_agent.orchestration.budget import BranchBudget
from deepresearch_agent.tools.reliable_execution import RunToolContext


@dataclass
class SearchQuota:
    limit: int
    used: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def consume(self) -> bool:
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


@dataclass
class RunScope:
    tool_context: RunToolContext
    search_quota: SearchQuota
    branch_budget: BranchBudget | None = None

ContractPredicate = Callable[[Mapping[str, Any], Mapping[str, Any]], bool]


@dataclass(frozen=True)
class ContractField:
    """One typed state path consumed by a node."""

    expected_type: type[Any] | tuple[type[Any], ...]
    required: bool = True

    @property
    def expected_name(self) -> str:
        expected = self.expected_type
        if isinstance(expected, tuple):
            return " | ".join(item.__name__ for item in expected)
        return expected.__name__


@dataclass(frozen=True)
class ContractInvariant:
    """An executable assertion spanning a node boundary."""

    name: str
    predicate: ContractPredicate
    expectation: str


@dataclass(frozen=True)
class NodeContract:
    """Declarative boundary contract for one LangGraph node."""

    name: str
    consumes: Mapping[str, ContractField] = field(default_factory=dict)
    produces: frozenset[str] = frozenset()
    invariants: tuple[ContractInvariant, ...] = ()
    decision_node: bool = False


@dataclass(frozen=True)
class ContractGraph:
    """The minimal topology view needed for build-time contract validation."""

    edges: tuple[tuple[str, str], ...]
    injected_paths: frozenset[str] = frozenset()


class ContractViolationError(RuntimeError):
    """Structured, redacted contract failure that identifies the faulty node."""

    def __init__(
        self,
        *,
        node: str,
        contract_item: str,
        expected: str,
        actual: str,
        state_snapshot: Mapping[str, Any],
    ) -> None:
        self.node = node
        self.contract_item = contract_item
        self.expected = expected
        self.actual = actual
        self.state_snapshot = dict(state_snapshot)
        super().__init__(self._message())

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": "orchestration_contract_violation",
            "node": self.node,
            "contract_item": self.contract_item,
            "expected": self.expected,
            "actual": self.actual,
            "state_snapshot": self.state_snapshot,
        }

    def _message(self) -> str:
        return redact(
            json.dumps(
                self.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )


class DecisionGate:
    """Require a decision node to append at least one AgentDecision."""

    @staticmethod
    def validate(
        node: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> None:
        before_count = _decision_count(before)
        after_count = _decision_count(after)
        if after_count <= before_count:
            raise ContractViolationError(
                node=node,
                contract_item="decision_gate",
                expected="at least one new AgentDecision",
                actual=f"before={before_count}, after={after_count}",
                state_snapshot=_state_key_snapshot(after),
            )


def validate_contract_graph(
    contracts: Mapping[str, NodeContract],
    graph: ContractGraph,
) -> None:
    """Fail graph construction when a consumed path has no prior producer."""

    known_nodes = set(contracts)
    for source, target in graph.edges:
        if source not in known_nodes or target not in known_nodes:
            raise ValueError(f"Contract graph edge references unknown node: {source}->{target}")

    for node_name, contract in contracts.items():
        ancestors = _ancestors(node_name, graph.edges)
        available: set[str] = set(graph.injected_paths)
        for ancestor in ancestors:
            available.update(contracts[ancestor].produces)
        for path in contract.consumes:
            if path not in available:
                raise ContractViolationError(
                    node=node_name,
                    contract_item=f"consumes:{path}",
                    expected="a preceding node or LangGraph Send producer",
                    actual="no producer found in contract graph",
                    state_snapshot={"ancestor_nodes": sorted(ancestors)},
                )


def enforce_node_contract(
    contract: NodeContract,
    node: Callable[..., Mapping[str, Any]],
) -> Callable[..., Mapping[str, Any]]:
    """Wrap a LangGraph node without changing its scheduling semantics."""

    def contracted(
        graph_state: Mapping[str, Any], runtime: Any = None
    ) -> Mapping[str, Any]:
        _validate_consumes(contract, graph_state)
        result = node(graph_state, runtime) if runtime is not None else node(graph_state)
        if not isinstance(result, Mapping):
            raise ContractViolationError(
                node=contract.name,
                contract_item="node_result",
                expected="mapping",
                actual=type(result).__name__,
                state_snapshot=_state_key_snapshot(graph_state),
            )
        _validate_produces(contract, result)
        merged = dict(graph_state)
        merged.update(result)
        _validate_invariants(contract, graph_state, merged)
        if contract.decision_node:
            DecisionGate.validate(contract.name, graph_state, merged)
        return result

    return contracted


def _validate_consumes(contract: NodeContract, graph_state: Mapping[str, Any]) -> None:
    for path, requirement in contract.consumes.items():
        present, value = _resolve_path(graph_state, path)
        if not present:
            if not requirement.required:
                continue
            raise ContractViolationError(
                node=contract.name,
                contract_item=f"consumes:{path}",
                expected=requirement.expected_name,
                actual="missing",
                state_snapshot=_state_key_snapshot(graph_state),
            )
        if not isinstance(value, requirement.expected_type):
            raise ContractViolationError(
                node=contract.name,
                contract_item=f"consumes:{path}",
                expected=requirement.expected_name,
                actual=type(value).__name__,
                state_snapshot=_state_key_snapshot(graph_state),
            )


def _validate_produces(contract: NodeContract, result: Mapping[str, Any]) -> None:
    for path in contract.produces:
        present, _ = _resolve_path(result, path)
        if not present:
            raise ContractViolationError(
                node=contract.name,
                contract_item=f"produces:{path}",
                expected="path written by node result",
                actual="missing",
                state_snapshot=_state_key_snapshot(result),
            )


def _validate_invariants(
    contract: NodeContract,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    for invariant in contract.invariants:
        try:
            valid = invariant.predicate(before, after)
        except Exception as exc:
            raise ContractViolationError(
                node=contract.name,
                contract_item=f"invariant:{invariant.name}",
                expected=invariant.expectation,
                actual=f"predicate raised {type(exc).__name__}",
                state_snapshot=_state_key_snapshot(after),
            ) from exc
        if not valid:
            raise ContractViolationError(
                node=contract.name,
                contract_item=f"invariant:{invariant.name}",
                expected=invariant.expectation,
                actual="predicate returned false",
                state_snapshot=_state_key_snapshot(after),
            )


def _resolve_path(state: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = state
    for segment in path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                return False, None
            current = current[segment]
        elif hasattr(current, segment):
            current = getattr(current, segment)
        else:
            return False, None
    return True, current


def _ancestors(node: str, edges: Sequence[tuple[str, str]]) -> set[str]:
    reverse: dict[str, list[str]] = {}
    for source, target in edges:
        reverse.setdefault(target, []).append(source)
    found: set[str] = set()
    queue = deque(reverse.get(node, []))
    while queue:
        current = queue.popleft()
        if current in found or current == node:
            continue
        found.add(current)
        queue.extend(reverse.get(current, []))
    return found


def _decision_count(state: Mapping[str, Any]) -> int:
    present, decisions = _resolve_path(state, "research_state.agent_decisions")
    if not present or not isinstance(decisions, list):
        return 0
    return len(decisions)


def _state_key_snapshot(state: Mapping[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "top_level_keys": sorted(redact(str(key)) for key in state),
    }
    present, research_state = _resolve_path(state, "research_state")
    if present and isinstance(research_state, Mapping):
        snapshot["research_state_keys"] = sorted(
            redact(str(key)) for key in research_state
        )
        for key in (
            "sources",
            "evidence_store",
            "retry_queue",
            "agent_decisions",
        ):
            value = research_state.get(key)
            if isinstance(value, (list, dict)):
                snapshot[f"{key}_count"] = len(value)
    return snapshot
