from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.orchestration import (
    ContractField,
    ContractGraph,
    ContractInvariant,
    ContractViolationError,
    NodeContract,
    enforce_node_contract,
    validate_contract_graph,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

class OrchestrationContractTest(unittest.TestCase):
    def test_graph_build_rejects_consume_without_preceding_producer(self) -> None:
        contracts = {
            "a": NodeContract(name="a", produces=frozenset({"state.a"})),
            "b": NodeContract(
                name="b",
                consumes={"state.missing": ContractField(str)},
            ),
        }

        with self.assertRaises(ContractViolationError) as caught:
            validate_contract_graph(
                contracts,
                ContractGraph(edges=(("a", "b"),)),
            )

        payload = caught.exception.as_dict()
        self.assertEqual(payload["node"], "b")
        self.assertEqual(payload["contract_item"], "consumes:state.missing")
        self.assertIn("no producer", payload["actual"])

    def test_runtime_rejects_missing_consumed_path_with_location(self) -> None:
        contract = NodeContract(
            name="consumer",
            consumes={"research_state.plan": ContractField(dict)},
        )
        node = enforce_node_contract(contract, lambda state: state)

        with self.assertRaises(ContractViolationError) as caught:
            node({"research_state": {"topic": "secret@example.com"}})

        message = str(caught.exception)
        self.assertIn('"node": "consumer"', message)
        self.assertIn("consumes:research_state.plan", message)
        self.assertIn("state_snapshot", message)
        self.assertNotIn("secret@example.com", message)

    def test_runtime_rejects_missing_produced_path(self) -> None:
        contract = NodeContract(
            name="producer",
            produces=frozenset({"research_state.result"}),
        )
        node = enforce_node_contract(
            contract,
            lambda _state: {"research_state": {}},
        )

        with self.assertRaises(ContractViolationError) as caught:
            node({"research_state": {}})

        self.assertEqual(
            caught.exception.contract_item,
            "produces:research_state.result",
        )
        self.assertEqual(caught.exception.actual, "missing")

    def test_runtime_rejects_broken_invariant(self) -> None:
        contract = NodeContract(
            name="mutator",
            invariants=(
                ContractInvariant(
                    name="identity",
                    predicate=lambda before, after: (
                        before["research_state"]["research_id"]
                        == after["research_state"]["research_id"]
                    ),
                    expectation="research_id remains unchanged",
                ),
            ),
        )
        node = enforce_node_contract(
            contract,
            lambda _state: {"research_state": {"research_id": "changed"}},
        )

        with self.assertRaises(ContractViolationError) as caught:
            node({"research_state": {"research_id": "original"}})

        self.assertEqual(
            caught.exception.contract_item,
            "invariant:identity",
        )
        self.assertIn("research_id remains unchanged", str(caught.exception))

    def test_decision_gate_rejects_decision_node_without_new_decision(self) -> None:
        contract = NodeContract(name="decider", decision_node=True)
        node = enforce_node_contract(contract, lambda state: state)

        with self.assertRaises(ContractViolationError) as caught:
            node({"research_state": {"agent_decisions": []}})

        self.assertEqual(caught.exception.contract_item, "decision_gate")
        self.assertIn("AgentDecision", caught.exception.expected)

    def test_all_current_nodes_have_contracts_and_footnote_handoff_is_explicit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    execution_mode="deterministic",
                    structured_logging_enabled=False,
                    run_manifest_enabled=False,
                )
            )

        self.assertEqual(
            set(engine.node_contracts),
            {
                "entry",
                "planner",
                "research_prepare",
                "research_one",
                "research_join",
                "extractor",
                "critic",
                "reflector",
                "research_loop_decide",
                "research_refine",
                "retry_prepare",
                "retry_one",
                "retry_join",
                "reporter",
                "evaluator",
            },
        )
        self.assertIn(
            "research_state.report_footnote_evidence",
            engine.node_contracts["reporter"].produces,
        )
        self.assertIn(
            "research_state.report_footnote_evidence",
            engine.node_contracts["evaluator"].consumes,
        )


if __name__ == "__main__":
    unittest.main()
