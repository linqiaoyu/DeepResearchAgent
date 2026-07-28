from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.memory import ContextWorkingMemory
from deepresearch_agent.orchestration import RunScope, SearchQuota
from deepresearch_agent.reporting import ReporterContextBuilder
from deepresearch_agent.schemas import (
    Evidence,
    ReportClaim,
    ReportDraft,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import FixtureSearchTool, RunToolContext
from deepresearch_agent.workflow import DeepResearchEngine


def _state() -> ResearchState:
    state = ResearchState(topic="cross-domain research")
    state.plan = ResearchPlan(
        topic=state.topic,
        sub_questions=[
            SubQuestion(id="q", question="question", search_queries=["query"])
        ],
    )
    state.evidence_store = [
        Evidence(
            id=item_id,
            research_id=state.research_id,
            sub_question_id="q",
            claim=f"claim {item_id}",
            claim_type="fact",
            source_url=f"https://{item_id}.example/source",
            source_title=f"source {item_id}",
            source_pub_date=date(2026, 7, 1),
            extract_text=("topic " * 40) + item_id,
        )
        for item_id in ("e1", "e2")
    ]
    return state


class _CapturingLLM:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, **kwargs: object) -> SimpleNamespace:
        self.messages = list(kwargs["messages"])
        self.calls.append(self.messages)
        return SimpleNamespace(
            parsed=ReportDraft(
                summary="Summary without numbers.",
                key_findings=[
                    ReportClaim(text="claim e1", evidence_ids=["e1"])
                ],
            ),
            repair_attempts=0,
        )


class AgentCoreArchitectureTests(unittest.TestCase):
    def test_engine_accepts_a_domain_specific_fact_renderer(self) -> None:
        class LegalFactRenderer:
            def render(self, state: ResearchState) -> object:
                raise AssertionError(f"not called during construction: {state.topic}")

            def is_supported(self, *_args: object, **_kwargs: object) -> bool:
                return True

        renderer = LegalFactRenderer()
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                ),
                grounded_fact_renderer=renderer,  # type: ignore[arg-type]
            )
            try:
                self.assertIs(
                    engine.reporter.grounded_fact_renderer,
                    renderer,
                )
            finally:
                engine._checkpoint_conn.close()

    def test_working_memory_is_prompt_view_not_canonical_store(self) -> None:
        state = _state()
        canonical_ids = [item.id for item in state.evidence_store]
        context = ReporterContextBuilder(ContextWorkingMemory()).build(
            state,
            enabled=True,
            budget=1,
            as_of=date(2026, 7, 26),
        )

        self.assertLess(len(context.evidence), len(state.evidence_store))
        self.assertEqual(
            [item.id for item in state.evidence_store],
            canonical_ids,
        )
        activity = state.metadata["component_activity"]["working_memory"]
        self.assertTrue(
            activity["events"][-1]["outputs"]["canonical_evidence_preserved"]
        )

    def test_reporter_packs_prompt_but_renders_canonical_footnotes(self) -> None:
        state = _state()
        client = _CapturingLLM()
        reporter = ReporterAgent(llm_client=client)

        report = reporter.report(
            state,
            context_evidence=[state.evidence_store[0]],
        )

        payload = json.loads(client.messages[-1]["content"])
        self.assertEqual(
            [item["id"] for item in payload["evidence"]],
            ["e1"],
        )
        self.assertEqual(set(state.report_footnote_evidence.values()), {"e1", "e2"})
        self.assertIn("https://e2.example/source", report)

    def test_citation_repair_cannot_bypass_packed_evidence_view(self) -> None:
        class RepairingLLM(_CapturingLLM):
            def complete(self, **kwargs: object) -> SimpleNamespace:
                self.messages = list(kwargs["messages"])
                self.calls.append(self.messages)
                return SimpleNamespace(
                    parsed=ReportDraft(
                        summary="Summary without numbers.",
                        key_findings=[
                            ReportClaim(
                                text="claim e1",
                                evidence_ids=[] if len(self.calls) == 1 else ["e1"],
                            )
                        ],
                    ),
                    repair_attempts=0,
                )

        state = _state()
        client = RepairingLLM()
        reporter = ReporterAgent(llm_client=client)

        reporter.report(
            state,
            context_evidence=[state.evidence_store[0]],
        )

        self.assertEqual(len(client.calls), 2)
        repair_payload = json.loads(client.calls[1][-1]["content"])
        self.assertEqual(
            [item["id"] for item in repair_payload["evidence_catalog"]],
            ["e1"],
        )
        self.assertNotIn("e2", client.calls[1][-1]["content"])

    def test_fixed_capability_mode_executes_disclosure_and_fetch(self) -> None:
        class Disclosure:
            def search(self, *_args: object, **_kwargs: object) -> list[object]:
                return []

        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    runs_root=Path(tmp) / "runs",
                    dynamic_capability_enabled=False,
                    structured_logging_enabled=False,
                ),
                search_tool=FixtureSearchTool(),
                disclosure_source=Disclosure(),
            )
            state = _state()
            captured: dict[str, object] = {}

            def research_with_budget(
                _sub_question: SubQuestion,
                **kwargs: object,
            ) -> tuple[list[object], list[object], int, bool, list[object]]:
                captured.update(kwargs)
                return [], [], 0, False, []

            engine.researcher.research_with_budget = research_with_budget  # type: ignore[method-assign]
            try:
                engine._research_one_node(
                    {
                        "research_state": engine._dump_state(state),
                        "fanout_sub_question": state.plan.sub_questions[0].model_dump(
                            mode="json"
                        ),
                    },
                    run_scope=RunScope(
                        tool_context=RunToolContext.for_run(),
                        search_quota=SearchQuota(engine.researcher.max_searches_per_run),
                    ),
                )
            finally:
                engine._checkpoint_conn.close()

        self.assertTrue(captured["enable_disclosure"])
        self.assertTrue(captured["enable_web_fetch"])
        self.assertTrue(captured["enable_web_search"])

    def test_shared_engine_serializes_mutable_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    runs_root=Path(tmp) / "runs",
                    structured_logging_enabled=False,
                ),
                search_tool=FixtureSearchTool(),
            )
            active = 0
            max_active = 0
            counter_lock = threading.Lock()

            def fake_run_once(**_kwargs: object) -> ResearchState:
                nonlocal active, max_active
                with counter_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.03)
                with counter_lock:
                    active -= 1
                return ResearchState(topic="done")

            engine._run_once = fake_run_once  # type: ignore[method-assign]
            threads = [
                threading.Thread(target=engine.run, kwargs={"topic": str(index)})
                for index in range(2)
            ]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            finally:
                engine._checkpoint_conn.close()

        self.assertEqual(max_active, 1)

    def test_independent_request_engines_share_wal_checkpoint_safely(self) -> None:
        """Request-scoped engines must not regress to sqlite's five-second lock."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                structured_logging_enabled=False,
            )
            barrier = threading.Barrier(8)
            failures: list[BaseException] = []
            failures_lock = threading.Lock()

            def run_request(index: int) -> None:
                engine: DeepResearchEngine | None = None
                try:
                    barrier.wait(timeout=5)
                    engine = DeepResearchEngine(
                        settings=settings,
                        search_tool=FixtureSearchTool(),
                    )
                    engine.run(topic=f"request {index}")
                except BaseException as exc:
                    with failures_lock:
                        failures.append(exc)
                finally:
                    if engine is not None:
                        engine.close()

            threads = [
                threading.Thread(target=run_request, args=(index,))
                for index in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
