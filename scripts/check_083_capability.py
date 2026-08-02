"""Round-083 deterministic check for financial-intent capability selection."""

from __future__ import annotations

from deepresearch_agent.schemas import ResearchState, SubQuestion
from deepresearch_agent.tools import (
    DeterministicCapabilitySelector,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    build_capability_registry,
)


def _selection(question: str):
    selector = DeterministicCapabilitySelector(build_capability_registry(
        search_provider=FixtureSearchTool(),
        structured_data_provider=FixtureStructuredDataProvider(),
    ))
    return selector.select(
        ResearchState(topic="round-083"),
        SubQuestion(id="check", question=question, search_queries=[]),
    )


def main() -> int:
    english = _selection("PDD 2024 annual report revenue and gross margin")
    chinese = _selection("蔚来 2024 年年报的营收与毛利情况")
    narrative = _selection("How does the market work?")
    print(f"english_financial_type={english.sub_question_type}")
    print(f"english_structured_rejected={int('structured_data_provider' in english.rejected_capabilities)}")
    print(f"chinese_financial_type={chinese.sub_question_type}")
    print(f"chinese_structured_rejected={int('structured_data_provider' in chinese.rejected_capabilities)}")
    print(f"narrative_structured_rejected={int('structured_data_provider' in narrative.rejected_capabilities)}")
    return int(not (
        english.sub_question_type == chinese.sub_question_type == "financial_metric"
        and "structured_data_provider" not in english.rejected_capabilities
        and "structured_data_provider" not in chinese.rejected_capabilities
        and narrative.sub_question_type == "narrative"
        and "structured_data_provider" in narrative.rejected_capabilities
    ))


if __name__ == "__main__":
    raise SystemExit(main())
