from __future__ import annotations

import re
from uuid import uuid5, NAMESPACE_URL

from deepresearch_agent.schemas import Evidence, Source, SubQuestion

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
NUMBER_RE = re.compile(r"(\$?\d+(?:\.\d+)?%?|\d+(?:\.\d+)?)")


class ExtractorAgent:
    def extract(self, research_id: str, sub_question: SubQuestion, sources: list[Source]) -> list[Evidence]:
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

