"""Finance-specific deterministic planning and structured-request policy."""

from __future__ import annotations

import re

from deepresearch_agent.schemas import ResearchPlan, StructuredDataRequest, SubQuestion


_CAPABILITIES = {"symbol_resolve", "financial_indicators", "price_history"}
_METRIC_TERMS = (
    "营业收入", "营收", "营业成本", "主营业务毛利率", "毛利率",
    "归母净利润", "净利润", "资产负债", "现金流", "每股收益",
    "净资产收益率",
)
_LISTED_COMPANIES = {
    "贵州茅台": "600519",
    "宁德时代": "300750",
    "中国平安": "601318",
}


class FinancePlanning:
    def deterministic_plan(self, topic: str, depth_level: int) -> ResearchPlan | None:
        request = self._metric_request(topic)
        if request is None:
            return None
        code, company_name, metrics = request
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

    def propagate_identity(self, plan: ResearchPlan, topic: str) -> ResearchPlan:
        request = self._metric_request(topic)
        if request is None:
            return plan
        code, company_name, metrics = request
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
            item
            for item in target.structured_data_requests
            if item.capability != "financial_indicators"
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
        updated[target_index] = target.model_copy(
            update={
                "question": topic,
                "search_queries": list(
                    dict.fromkeys([f"{code} 年度报告", *target.search_queries])
                ),
                "structured_data_requests": existing,
            }
        )
        return plan.model_copy(
            update={"sub_questions": [updated[target_index]], "estimated_sources": 3}
        )

    def valid_structured_request(self, request: StructuredDataRequest) -> bool:
        capability = request.capability.strip()
        if capability not in _CAPABILITIES:
            return False
        if capability == "symbol_resolve":
            return bool(request.company_name)
        if capability == "financial_indicators":
            return bool(request.symbol or request.company_name)
        return bool(
            (request.symbol or request.company_name)
            and request.start_date
            and request.end_date
        )

    def _metric_request(self, topic: str) -> tuple[str, str | None, list[str]] | None:
        matched = [term for term in _METRIC_TERMS if term in topic]
        metrics = [
            term
            for term in matched
            if not any(term != other and term in other for other in matched)
        ]
        metrics = ["主营业务毛利率" if term == "毛利率" else term for term in metrics]
        if not metrics:
            return None
        code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", topic)
        company_name = next((name for name in _LISTED_COMPANIES if name in topic), None)
        if code_match is None and company_name is None:
            return None
        code = code_match.group(1) if code_match else _LISTED_COMPANIES[company_name]
        return code, company_name, metrics

    @staticmethod
    def _annual_periods(topic: str) -> list[str]:
        return [f"{year}1231" for year in dict.fromkeys(re.findall(r"20\d{2}", topic))]
