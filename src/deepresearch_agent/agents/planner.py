from __future__ import annotations

import json
import re

from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.schemas import ResearchPlan, StructuredDataRequest, SubQuestion
from deepresearch_agent.settings import Settings, project_root


class PlannerAgent:
    STRUCTURED_CAPABILITIES = {"symbol_resolve", "financial_indicators", "price_history"}
    FINANCIAL_METRIC_TERMS = (
        "营业收入", "营收", "营业成本", "主营业务毛利率", "毛利率",
        "归母净利润", "净利润", "资产负债", "现金流", "每股收益",
        "净资产收益率",
    )
    LISTED_COMPANIES = {
        "贵州茅台": "600519",
        "宁德时代": "300750",
        "中国平安": "601318",
    }

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.settings = settings
        self.last_stats: dict[str, int | bool | str] = {}
        self._last_invalid_structured_request_count = 0

    def plan(self, topic: str, depth_level: int = 2, research_id: str | None = None) -> ResearchPlan:
        if self.llm_client and research_id and self.settings:
            try:
                return self._llm_plan(topic, depth_level, research_id)
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
        return self._deterministic_plan(topic, depth_level)

    def _deterministic_plan(self, topic: str, depth_level: int = 2) -> ResearchPlan:
        financial_request = self._financial_metric_request(topic)
        if financial_request is not None:
            code, company_name, metrics = financial_request
            return ResearchPlan(
                topic=topic,
                depth_level=depth_level,
                sub_questions=[
                    SubQuestion(
                        id="financial_metrics",
                        question=topic,
                        search_queries=[f"{code} {metric} 年度报告" for metric in metrics],
                        expected_source_types=["official"],
                        structured_data_requests=[
                            StructuredDataRequest(
                                capability="financial_indicators",
                                company_name=company_name,
                                symbol=code,
                                periods=self._annual_periods(topic),
                                metrics=metrics,
                            )
                        ],
                        priority=5,
                    )
                ],
                estimated_sources=3,
                success_criteria=[
                    "Financial metrics are traceable to a first-party disclosure.",
                    "Every key finding has at least one source-backed citation.",
                ],
            )
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

    def _financial_metric_request(
        self, topic: str
    ) -> tuple[str, str | None, list[str]] | None:
        """Recognise only explicit A-share financial-metric questions.

        Deliberately excluding generic terms such as ``业绩`` preserves the
        frozen broad-research snapshots; this route is for a concrete metric
        request, not a loose company research topic.
        """
        matched_metrics = [
            term for term in self.FINANCIAL_METRIC_TERMS if term in topic
        ]
        metrics = [
            term
            for term in matched_metrics
            if not any(
                term != other and term in other
                for other in matched_metrics
            )
        ]
        metrics = [
            "主营业务毛利率" if term == "毛利率" else term
            for term in metrics
        ]
        if not metrics:
            return None
        code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", topic)
        company_name = next(
            (name for name in self.LISTED_COMPANIES if name in topic), None
        )
        if code_match is None and company_name is None:
            return None
        code = code_match.group(1) if code_match else self.LISTED_COMPANIES[company_name]
        return code, company_name, metrics

    def _annual_periods(self, topic: str) -> list[str]:
        years = dict.fromkeys(re.findall(r"20\d{2}", topic))
        return [f"{year}1231" for year in years]

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
        plan = self._propagate_financial_identity(plan, topic)
        self.last_stats = {
            "fallback": False,
            "repair_attempts": result.repair_attempts,
            "invalid_structured_data_requests": self._last_invalid_structured_request_count,
        }
        return plan

    def _normalize_plan(self, plan: ResearchPlan, topic: str, depth_level: int) -> ResearchPlan:
        assert self.settings is not None
        sub_questions = plan.sub_questions[: self.settings.llm_max_sub_questions]
        normalized: list[SubQuestion] = []
        invalid_count = 0
        seen_ids: set[str] = set()
        for index, sub_question in enumerate(sub_questions):
            subq_id = self._stable_id(sub_question.id or sub_question.question, index)
            while subq_id in seen_ids:
                subq_id = f"{subq_id}_{index + 1}"
            seen_ids.add(subq_id)
            structured_requests = self._valid_structured_requests(sub_question.structured_data_requests)
            invalid_count += len(sub_question.structured_data_requests) - len(structured_requests)
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
                    structured_data_requests=structured_requests,
                    priority=sub_question.priority,
                )
            )
        if not normalized:
            raise ValueError("Planner returned no sub-questions.")
        self._last_invalid_structured_request_count = invalid_count
        return ResearchPlan(
            topic=topic,
            depth_level=depth_level,
            sub_questions=normalized,
            estimated_sources=max(6, len(normalized) * 2),
            success_criteria=plan.success_criteria,
        )

    def _propagate_financial_identity(
        self, plan: ResearchPlan, topic: str
    ) -> ResearchPlan:
        """Attach deterministic issuer identity to the LLM's financial branch.

        The planner prompt remains the source of question decomposition.  For an
        explicit, recognised A-share metric request, the topic itself is the
        authoritative identity source; preserving it here lets downstream
        capability selection fail closed for every other question.
        """
        financial_request = self._financial_metric_request(topic)
        if financial_request is None:
            return plan
        code, company_name, metrics = financial_request
        target_index = next(
            (
                index
                for index, item in enumerate(plan.sub_questions)
                if any(term in item.question for term in metrics)
                or any(term in " ".join(item.search_queries) for term in metrics)
            ),
            0,
        )
        updated = list(plan.sub_questions)
        target = updated[target_index]
        existing = [
            request
            for request in target.structured_data_requests
            if request.capability != "financial_indicators"
        ]
        existing.insert(
            0,
            StructuredDataRequest(
                capability="financial_indicators",
                company_name=company_name,
                symbol=code,
                periods=self._annual_periods(topic),
                metrics=metrics,
            ),
        )
        annual_report_query = f"{code} 年度报告"
        updated[target_index] = target.model_copy(
            update={
                "question": topic,
                "search_queries": list(dict.fromkeys([
                    annual_report_query, *target.search_queries,
                ])),
                "structured_data_requests": existing,
            }
        )
        # An explicit issuer+metric lookup is one typed fact-retrieval branch.
        # Creative auxiliary branches such as market expectations can exhaust
        # web egress without helping the requested annual-report answer.
        # Narrative and event plans never enter this financial contract path.
        return plan.model_copy(
            update={
                "sub_questions": [updated[target_index]],
                "estimated_sources": 3,
            }
        )

    def _valid_structured_requests(
        self,
        requests: list[StructuredDataRequest],
    ) -> list[StructuredDataRequest]:
        return [request for request in requests if self._is_valid_structured_request(request)]

    def _is_valid_structured_request(self, request: StructuredDataRequest) -> bool:
        capability = request.capability.strip()
        if capability not in self.STRUCTURED_CAPABILITIES:
            return False
        if capability == "symbol_resolve":
            return bool(request.company_name)
        if capability == "financial_indicators":
            return bool(request.symbol or request.company_name)
        if capability == "price_history":
            return bool((request.symbol or request.company_name) and request.start_date and request.end_date)
        return False

    def _stable_id(self, value: str, index: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug[:48] or f"sub_question_{index + 1}"
