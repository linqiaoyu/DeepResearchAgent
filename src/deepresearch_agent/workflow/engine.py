from __future__ import annotations

import time

from deepresearch_agent.agents import CriticAgent, Evaluator, ExtractorAgent, PlannerAgent, ReporterAgent, ResearcherAgent
from deepresearch_agent.schemas import ResearchState, Source, SubQuestion, TodoItem
from deepresearch_agent.settings import Settings, load_settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import FixtureSearchTool


class DeepResearchEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        store: SQLiteStore | None = None,
        search_tool: FixtureSearchTool | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.store = store or SQLiteStore(self.settings.storage_path)
        self.search_tool = search_tool or FixtureSearchTool()
        self.planner = PlannerAgent()
        self.researcher = ResearcherAgent(self.search_tool)
        self.extractor = ExtractorAgent()
        self.critic = CriticAgent()
        self.reporter = ReporterAgent()
        self.evaluator = Evaluator()

    def run(
        self,
        topic: str | None = None,
        depth_level: int = 2,
        research_id: str | None = None,
        resume: bool = False,
        stop_after_phase: str | None = None,
    ) -> ResearchState:
        started = time.perf_counter()
        if resume:
            if not research_id:
                raise ValueError("research_id is required when resume=True")
            state = self.store.load_checkpoint(research_id)
            if not state:
                raise ValueError(f"No checkpoint found for research_id={research_id}")
            state.status = "running"
        else:
            if not topic:
                raise ValueError("topic is required for a new research run")
            state = ResearchState(topic=topic, depth_level=depth_level)
            self.store.save_checkpoint(state)

        while state.current_phase != "done":
            if state.current_phase == "planning":
                self._planning(state)
                if self._checkpoint_or_pause(state, "planning", "researching", stop_after_phase):
                    return state
            elif state.current_phase == "researching":
                self._researching(state)
                if self._checkpoint_or_pause(state, "researching", "extracting", stop_after_phase):
                    return state
            elif state.current_phase == "extracting":
                self._extracting(state)
                if self._checkpoint_or_pause(state, "extracting", "critiquing", stop_after_phase):
                    return state
            elif state.current_phase == "critiquing":
                self._critiquing(state)
                if self._checkpoint_or_pause(state, "critiquing", "reporting", stop_after_phase):
                    return state
            elif state.current_phase == "reporting":
                state.final_report = self.reporter.report(state)
                state.draft_report = state.final_report
                state.token_used += self._estimate_tokens(state.final_report)
                if self._checkpoint_or_pause(state, "reporting", "evaluating", stop_after_phase):
                    return state
            elif state.current_phase == "evaluating":
                state.evaluation = self.evaluator.evaluate(state, started_at=started)
                self.store.save_evaluation(state.evaluation)
                if self._checkpoint_or_pause(state, "evaluating", "done", stop_after_phase):
                    return state
            else:
                raise ValueError(f"Unknown phase: {state.current_phase}")

        state.status = "done"
        self.store.save_checkpoint(state)
        return state

    def _planning(self, state: ResearchState) -> None:
        state.plan = self.planner.plan(state.topic, state.depth_level)
        state.todo_list = [
            TodoItem(id=item.id, title=item.question, status="pending")
            for item in state.plan.sub_questions
        ]
        state.pending_tasks = [item.id for item in state.plan.sub_questions]
        state.token_used += 900
        state.cost_used += 0.002

    def _researching(self, state: ResearchState) -> None:
        if not state.plan:
            raise ValueError("Researching requires a plan.")
        source_by_url: dict[str, Source] = {source.url: source for source in state.sources}
        sources_by_subquestion = dict(state.metadata.get("sources_by_subquestion", {}))
        for sub_question in state.plan.sub_questions:
            sources, records = self.researcher.research(sub_question)
            state.search_records.extend(records)
            sources_by_subquestion[sub_question.id] = [source.url for source in sources]
            for source in sources:
                source_by_url[source.url] = source
            state.completed_tasks.append(sub_question.id)
        state.sources = list(source_by_url.values())
        state.metadata["sources_by_subquestion"] = sources_by_subquestion
        state.pending_tasks = []
        for item in state.todo_list:
            item.status = "done"
        state.token_used += 1_500
        state.cost_used += 0.004

    def _extracting(self, state: ResearchState) -> None:
        if not state.plan:
            raise ValueError("Extracting requires a plan.")
        evidence_by_id = {item.id: item for item in state.evidence_store}
        for sub_question in state.plan.sub_questions:
            relevant_sources = self._sources_for_subquestion(state, sub_question.id)
            extracted = self.extractor.extract(state.research_id, sub_question, relevant_sources)
            for item in extracted:
                evidence_by_id[item.id] = item
        state.evidence_store = list(evidence_by_id.values())
        self.store.add_evidence_many(state.evidence_store)
        state.token_used += 2_300
        state.cost_used += 0.006

    def _critiquing(self, state: ResearchState) -> None:
        if not state.plan:
            raise ValueError("Critiquing requires a plan.")
        while True:
            state.critic_report = self.critic.critique(state)
            state.critic_iteration = state.critic_report.iteration
            state.retry_queue = state.critic_report.retry_tasks
            if state.critic_report.passed or state.critic_iteration >= self.settings.max_critic_iter:
                if not state.critic_report.passed and state.critic_iteration >= self.settings.max_critic_iter:
                    state.critic_report.forced_pass = True
                    state.critic_report.passed = True
                break
            self._execute_retry_tasks(state)
        state.token_used += 1_700 * max(state.critic_iteration, 1)
        state.cost_used += 0.005 * max(state.critic_iteration, 1)

    def _execute_retry_tasks(self, state: ResearchState) -> None:
        if not state.plan:
            return
        source_by_url: dict[str, Source] = {source.url: source for source in state.sources}
        evidence_by_id = {item.id: item for item in state.evidence_store}
        for task in state.retry_queue:
            target_subq = self._retry_target_subquestion(state, task.sub_question_id)
            sources, record = self.researcher.retry(task.query, task.source_type)
            state.search_records.append(record)
            for source in sources:
                source_by_url[source.url] = source
            extracted = self.extractor.extract(state.research_id, target_subq, sources)
            for item in extracted:
                evidence_by_id[item.id] = item
            task.completed = True
        state.sources = list(source_by_url.values())
        state.evidence_store = list(evidence_by_id.values())
        self.store.add_evidence_many(state.evidence_store)

    def _retry_target_subquestion(
        self,
        state: ResearchState,
        sub_question_id: str | None,
    ) -> SubQuestion:
        if not state.plan or not state.plan.sub_questions:
            raise ValueError("Retry extraction requires a plan with sub-questions.")
        if sub_question_id:
            for sub_question in state.plan.sub_questions:
                if sub_question.id == sub_question_id:
                    return sub_question
        return state.plan.sub_questions[-1]

    def _sources_for_subquestion(self, state: ResearchState, sub_question_id: str) -> list[Source]:
        if not state.plan:
            return []
        source_urls = set(state.metadata.get("sources_by_subquestion", {}).get(sub_question_id, []))
        if source_urls:
            return [source for source in state.sources if source.url in source_urls]
        sub_question = next(item for item in state.plan.sub_questions if item.id == sub_question_id)
        query_text = " ".join([sub_question.question, *sub_question.search_queries]).lower()
        matches = [
            source for source in state.sources
            if any(term.lower() in f"{source.title} {source.content}".lower() for term in query_text.split()[:16])
        ]
        return matches[:4] or state.sources[:2]

    def _checkpoint_or_pause(
        self,
        state: ResearchState,
        completed_phase: str,
        next_phase: str,
        stop_after_phase: str | None,
    ) -> bool:
        state.current_phase = next_phase
        if stop_after_phase == completed_phase:
            state.status = "paused"
            self.store.save_checkpoint(state)
            return True
        self.store.save_checkpoint(state)
        return False

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
