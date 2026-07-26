from __future__ import annotations

import json
import re
from uuid import uuid5, NAMESPACE_URL

from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.schemas import Evidence, ExtractedClaim, ExtractedClaims, Source, SubQuestion
from deepresearch_agent.security import detect_injection, wrap_untrusted
from deepresearch_agent.settings import project_root
from deepresearch_agent.agents.financial_table_extractor import (
    authoritative_financial_backfills,
    merge_authoritative_financial_evidence,
)

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
NUMBER_RE = re.compile(r"(\$?\d+(?:\.\d+)?%?|\d+(?:\.\d+)?)")
PDF_PAGE_MARKER_RE = re.compile(r"\[\[PDF_PAGE=(\d+)\]\]")


class ExtractorAgent:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        injection_guard_enabled: bool = False,
    ) -> None:
        self.llm_client = llm_client
        self.injection_guard_enabled = injection_guard_enabled
        self.last_stats: dict[str, int | bool | str] = {}

    def extract(self, research_id: str, sub_question: SubQuestion, sources: list[Source]) -> list[Evidence]:
        if self.llm_client:
            try:
                evidence = self._llm_extract(
                    research_id,
                    sub_question,
                    sources,
                )
                return self._with_authoritative_backfills(
                    research_id,
                    sub_question,
                    sources,
                    evidence,
                )
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
        evidence = self._deterministic_extract(
            research_id,
            sub_question,
            sources,
        )
        return self._with_authoritative_backfills(
            research_id,
            sub_question,
            sources,
            evidence,
        )

    def _with_authoritative_backfills(
        self,
        research_id: str,
        sub_question: SubQuestion,
        sources: list[Source],
        evidence: list[Evidence],
    ) -> list[Evidence]:
        backfills = authoritative_financial_backfills(
            research_id,
            sub_question,
            sources,
        )
        self.last_stats = {
            **self.last_stats,
            "authoritative_financial_backfills": len(backfills),
        }
        return merge_authoritative_financial_evidence(
            evidence,
            backfills,
        )

    def _deterministic_extract(
        self,
        research_id: str,
        sub_question: SubQuestion,
        sources: list[Source],
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        for source in sources:
            finding = detect_injection(source.content) if self.injection_guard_enabled else None
            sentences = [s.strip() for s in SENTENCE_RE.split(source.content) if len(s.strip()) > 30]
            for offset, sentence in enumerate(sentences[:4]):
                claim_type = self._classify(sentence)
                extract_offset_start = source.content.find(sentence)
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
                        source_page=self._source_page(
                            source.content,
                            extract_offset_start,
                        ),
                        extract_text=sentence,
                        extract_offset_start=max(0, extract_offset_start),
                        confidence=self._guarded_confidence(
                            self._confidence(sentence, source.credibility),
                            finding.risk_score if finding else 0.0,
                        ),
                        source_tier=source.source_tier,
                        content_truncated=source.content_truncated,
                        injection_risk_score=finding.risk_score if finding else 0.0,
                        injection_patterns=finding.patterns if finding else [],
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
                                    "published_at": source.published_at.isoformat() if source.published_at else "unknown",
                                    "content": (
                                        wrap_untrusted(source.content, source_url=source.url)
                                        if self.injection_guard_enabled
                                        else source.content
                                    ),
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
            finding = detect_injection(source.content) if self.injection_guard_enabled else None
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
                    source_page=self._source_page(
                        source.content,
                        source.content.find(claim.extract_text),
                    ),
                    extract_text=claim.extract_text,
                    extract_offset_start=source.content.find(claim.extract_text),
                    confidence=self._guarded_confidence(
                        claim.confidence,
                        finding.risk_score if finding else 0.0,
                    ),
                    source_tier=source.source_tier,
                    content_truncated=source.content_truncated,
                    numeric_fields=claim.numeric_fields,
                    numeric_fields_incomplete=numeric_fields_incomplete,
                    injection_risk_score=finding.risk_score if finding else 0.0,
                    injection_patterns=finding.patterns if finding else [],
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

    def _source_page(self, content: str, extract_offset_start: int) -> int | None:
        """Resolve the nearest preceding decoder page marker for one extract."""
        if extract_offset_start < 0:
            return None
        marker_at_start = PDF_PAGE_MARKER_RE.match(
            content,
            extract_offset_start,
        )
        if marker_at_start:
            return int(marker_at_start.group(1))
        matches = list(
            PDF_PAGE_MARKER_RE.finditer(
                content[:extract_offset_start]
            )
        )
        return int(matches[-1].group(1)) if matches else None

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

    def _guarded_confidence(self, confidence: float, risk_score: float) -> float:
        if risk_score < 0.5:
            return confidence
        return max(0.0, round(confidence * (1.0 - min(risk_score, 0.8) * 0.5), 3))
