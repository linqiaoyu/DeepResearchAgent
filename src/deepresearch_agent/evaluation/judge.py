from __future__ import annotations

import json
from statistics import median
from typing import Literal

from pydantic import Field

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.schemas import StrictModel
from deepresearch_agent.settings import project_root

JUDGE_WEIGHTS = {
    "fact_coverage": 0.35,
    "fact_accuracy": 0.25,
    "citation_support": 0.25,
    "synthesis_balance": 0.15,
}


class JudgeScore(StrictModel):
    fact_coverage: float = Field(ge=0, le=1)
    fact_accuracy: float = Field(ge=0, le=1)
    citation_support: float = Field(ge=0, le=1)
    synthesis_balance: float = Field(ge=0, le=1)
    reasons: dict[str, str] = Field(default_factory=dict)

    @property
    def weighted_score(self) -> float:
        return round(
            self.fact_coverage * JUDGE_WEIGHTS["fact_coverage"]
            + self.fact_accuracy * JUDGE_WEIGHTS["fact_accuracy"]
            + self.citation_support * JUDGE_WEIGHTS["citation_support"]
            + self.synthesis_balance * JUDGE_WEIGHTS["synthesis_balance"],
            4,
        )


class CitationSupportVerdict(StrictModel):
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["supported", "partially_supported", "unsupported"]
    reason: str


class CitationSupportResult(StrictModel):
    verdicts: list[CitationSupportVerdict] = Field(default_factory=list)

    @property
    def support_rate(self) -> float:
        if not self.verdicts:
            return 0.0
        values = {
            "supported": 1.0,
            "partially_supported": 0.5,
            "unsupported": 0.0,
        }
        return round(sum(values[item.status] for item in self.verdicts) / len(self.verdicts), 3)


def median_judge_score(samples: list[JudgeScore]) -> JudgeScore:
    if not samples:
        raise ValueError("median_judge_score requires at least one sample.")
    return JudgeScore(
        fact_coverage=median(item.fact_coverage for item in samples),
        fact_accuracy=median(item.fact_accuracy for item in samples),
        citation_support=median(item.citation_support for item in samples),
        synthesis_balance=median(item.synthesis_balance for item in samples),
        reasons={"aggregation": f"median of {len(samples)} samples"},
    )


class JudgeClient:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client
        self.prompt = (project_root() / "prompts" / "judge.md").read_text(encoding="utf-8")

    def score(self, run_id: str, case: dict, report: str, evidence: list[dict]) -> JudgeScore:
        result = self.llm_client.complete(
            role="judge",
            run_id=run_id,
            schema=JudgeScore,
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"case": case, "report": report, "evidence": evidence},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        if not isinstance(result.parsed, JudgeScore):
            raise ValueError("Judge did not return JudgeScore.")
        return result.parsed

    def citation_support(
        self,
        run_id: str,
        claims: list[dict],
        evidence: list[dict],
    ) -> CitationSupportResult:
        result = self.llm_client.complete(
            role="citation_support",
            run_id=run_id,
            schema=CitationSupportResult,
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"claims": claims, "evidence": evidence},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        if not isinstance(result.parsed, CitationSupportResult):
            raise ValueError("Citation support judge did not return CitationSupportResult.")
        return result.parsed
