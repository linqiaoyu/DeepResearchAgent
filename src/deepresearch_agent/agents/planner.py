from __future__ import annotations

import json
import re

from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.schemas import ResearchPlan, SubQuestion
from deepresearch_agent.settings import Settings, project_root


class PlannerAgent:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.settings = settings
        self.last_stats: dict[str, int | bool | str] = {}

    def plan(self, topic: str, depth_level: int = 2, research_id: str | None = None) -> ResearchPlan:
        if self.llm_client and research_id and self.settings:
            try:
                return self._llm_plan(topic, depth_level, research_id)
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
        return self._deterministic_plan(topic, depth_level)

    def _deterministic_plan(self, topic: str, depth_level: int = 2) -> ResearchPlan:
        base_dimensions = [
            (
                "market_pain",
                f"What concrete pain points make {topic} valuable?",
                ["industry report pain points", f"{topic} customer pain points", "market demand"],
                ["industry_report", "news", "official"],
            ),
            (
                "current_adoption",
                f"What is the current adoption state and production maturity of {topic}?",
                [f"{topic} adoption 2026", f"{topic} production case", "AI agent deployment"],
                ["official", "news", "industry_report"],
            ),
            (
                "players",
                f"Which major players and implementation paths define {topic}?",
                [f"{topic} major players", "Ant wealth management AI agent", "Revolut AI advisor"],
                ["company_report", "news", "official"],
            ),
            (
                "risk_governance",
                f"What risks, compliance constraints, and counterarguments matter for {topic}?",
                [f"{topic} regulatory risk", "AI financial advice compliance", "model risk governance"],
                ["official", "regulation", "industry_report"],
            ),
            (
                "evaluation",
                f"How should teams evaluate quality, citation accuracy, cost, and latency for {topic}?",
                ["AI agent evaluation citation accuracy", "RAG evaluation cost latency", "LLM-as-Judge"],
                ["paper", "official", "engineering_blog"],
            ),
        ]
        selected = base_dimensions[:3] if depth_level == 1 else base_dimensions[:4]
        if depth_level >= 3:
            selected = base_dimensions

        sub_questions = [
            SubQuestion(
                id=dimension_id,
                question=question,
                search_queries=queries,
                expected_source_types=source_types,
                priority=5 - idx if idx < 4 else 3,
            )
            for idx, (dimension_id, question, queries, source_types) in enumerate(selected)
        ]
        return ResearchPlan(
            topic=topic,
            depth_level=depth_level,
            sub_questions=sub_questions,
            estimated_sources=max(6, len(sub_questions) * 2),
            success_criteria=[
                "Every key finding has at least one source-backed citation.",
                "Time-sensitive financial claims prefer sources published within 12 months.",
                "The report includes a counterargument or risk section.",
                "Evaluation metrics include citation accuracy, relevance, faithfulness, cost, and latency.",
            ],
        )

    def _llm_plan(self, topic: str, depth_level: int, research_id: str) -> ResearchPlan:
        assert self.llm_client is not None
        assert self.settings is not None
        prompt = (project_root() / "prompts" / "planner.md").read_text(encoding="utf-8")
        result = self.llm_client.complete(
            role="planner",
            run_id=research_id,
            schema=ResearchPlan,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": topic,
                            "depth_level": depth_level,
                            "max_sub_questions": self.settings.llm_max_sub_questions,
                            "max_queries_per_sub_question": self.settings.llm_max_queries_per_sub_question,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        if not isinstance(result.parsed, ResearchPlan):
            raise ValueError("Planner did not return a ResearchPlan.")
        plan = self._normalize_plan(result.parsed, topic, depth_level)
        self.last_stats = {"fallback": False, "repair_attempts": result.repair_attempts}
        return plan

    def _normalize_plan(self, plan: ResearchPlan, topic: str, depth_level: int) -> ResearchPlan:
        assert self.settings is not None
        sub_questions = plan.sub_questions[: self.settings.llm_max_sub_questions]
        normalized: list[SubQuestion] = []
        seen_ids: set[str] = set()
        for index, sub_question in enumerate(sub_questions):
            subq_id = self._stable_id(sub_question.id or sub_question.question, index)
            while subq_id in seen_ids:
                subq_id = f"{subq_id}_{index + 1}"
            seen_ids.add(subq_id)
            normalized.append(
                SubQuestion(
                    id=subq_id,
                    question=sub_question.question,
                    search_queries=sub_question.search_queries[
                        : self.settings.llm_max_queries_per_sub_question
                    ],
                    expected_source_types=sub_question.expected_source_types[
                        : self.settings.llm_max_queries_per_sub_question
                    ],
                    priority=sub_question.priority,
                )
            )
        if not normalized:
            raise ValueError("Planner returned no sub-questions.")
        return ResearchPlan(
            topic=topic,
            depth_level=depth_level,
            sub_questions=normalized,
            estimated_sources=max(6, len(normalized) * 2),
            success_criteria=plan.success_criteria,
        )

    def _stable_id(self, value: str, index: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug[:48] or f"sub_question_{index + 1}"
