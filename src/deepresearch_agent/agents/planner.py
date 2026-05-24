from __future__ import annotations

from deepresearch_agent.schemas import ResearchPlan, SubQuestion


class PlannerAgent:
    def plan(self, topic: str, depth_level: int = 2) -> ResearchPlan:
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

