from __future__ import annotations

import json
import re
from uuid import uuid5, NAMESPACE_URL

from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.schemas import Evidence, ExtractedClaim, ExtractedClaims, Source, SubQuestion
from deepresearch_agent.settings import project_root

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
NUMBER_RE = re.compile(r"(\$?\d+(?:\.\d+)?%?|\d+(?:\.\d+)?)")


class ExtractorAgent:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.last_stats: dict[str, int | bool | str] = {}

    def extract(self, research_id: str, sub_question: SubQuestion, sources: list[Source]) -> list[Evidence]:
        if self.llm_client:
            try:
                return self._llm_extract(research_id, sub_question, sources)
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
        return self._deterministic_extract(research_id, sub_question, sources)

    def _deterministic_extract(
        self,
        research_id: str,
        sub_question: SubQuestion,
        sources: list[Source],
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        for source in sources:
            sentences = [s.strip() for s in SENTENCE_RE.split(source.content) if len(s.strip()) > 30]
            for offset, sentence in enumerate(sentences[:4]):
                claim_type = self._classify(sentence)
                evidence_id = str(uuid5(NAMESPACE_URL, f"{research_id}:{sub_question.id}:{source.url}:{offset}:{sentence}"))
                evidence.append(
                    Evidence(
                        id=evidence_id,
                        research_id=research_id,
                        sub_question_id=sub_question.id,
                        claim=sentence,
                        claim_type=claim_type,
                        source_url=source.url,
                        source_title=source.title,
                        source_pub_date=source.published_at,
                        extract_text=sentence,
                        extract_offset_start=offset,
                        confidence=self._confidence(sentence, source.credibility),
                    )
                )
        return evidence

    def _llm_extract(
        self,
        research_id: str,
        sub_question: SubQuestion,
        sources: list[Source],
    ) -> list[Evidence]:
        if not sources:
            self.last_stats = {"fallback": False, "invalid_extract_text": 0, "claims": 0}
            return []
        assert self.llm_client is not None
        source_by_url = {source.url: source for source in sources}
        prompt = (project_root() / "prompts" / "extractor.md").read_text(encoding="utf-8")
        result = self.llm_client.complete(
            role="extractor",
            run_id=research_id,
            schema=ExtractedClaims,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "sub_question": sub_question.model_dump(mode="json"),
                            "sources": [
                                {
                                    "title": source.title,
                                    "url": source.url,
                                    "source_type": source.source_type,
                                    "published_at": source.published_at.isoformat(),
                                    "content": source.content,
                                }
                                for source in sources
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        if not isinstance(result.parsed, ExtractedClaims):
            raise ValueError("Extractor did not return ExtractedClaims.")
        evidence: list[Evidence] = []
        invalid_extract_text = 0
        incomplete_numeric_fields = 0
        for index, claim in enumerate(result.parsed.claims):
            source = source_by_url.get(claim.source_url)
            if not source or claim.extract_text not in source.content:
                invalid_extract_text += 1
                continue
            numeric_fields_incomplete = self._numeric_fields_incomplete(claim)
            if numeric_fields_incomplete:
                incomplete_numeric_fields += 1
            evidence_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{research_id}:{sub_question.id}:{source.url}:{index}:{claim.claim}:{claim.extract_text}",
                )
            )
            evidence.append(
                Evidence(
                    id=evidence_id,
                    research_id=research_id,
                    sub_question_id=sub_question.id,
                    claim=claim.claim,
                    claim_type=claim.claim_type,
                    source_url=source.url,
                    source_title=source.title,
                    source_pub_date=source.published_at,
                    extract_text=claim.extract_text,
                    extract_offset_start=source.content.find(claim.extract_text),
                    confidence=claim.confidence,
                    numeric_fields=claim.numeric_fields,
                    numeric_fields_incomplete=numeric_fields_incomplete,
                )
            )
        self.last_stats = {
            "fallback": False,
            "invalid_extract_text": invalid_extract_text,
            "incomplete_numeric_fields": incomplete_numeric_fields,
            "claims": len(evidence),
            "repair_attempts": result.repair_attempts,
        }
        return evidence

    def _numeric_fields_incomplete(self, claim: ExtractedClaim) -> bool:
        if claim.claim_type != "data":
            return False
        if claim.numeric_fields is None:
            return True
        return not (
            claim.numeric_fields.entity
            and claim.numeric_fields.metric_name
            and claim.numeric_fields.value is not None
        )

    def _classify(self, sentence: str) -> str:
        lowered = sentence.lower()
        if NUMBER_RE.search(sentence):
            return "data"
        if any(term in lowered for term in ["expected", "may", "could", "预计", "可能", "projection"]):
            return "projection"
        if any(term in lowered for term in ["risk", "however", "constraint", "regulatory", "limitation", "合规"]):
            return "opinion"
        return "fact"

    def _confidence(self, sentence: str, credibility: float) -> float:
        signal = 0.1 if NUMBER_RE.search(sentence) else 0.0
        return min(0.95, max(0.55, credibility * 0.8 + signal))
