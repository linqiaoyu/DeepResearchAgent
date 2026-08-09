from __future__ import annotations

import json
import re
from uuid import uuid5, NAMESPACE_URL

from deepresearch_agent.domains.protocols import TableExtractionDomain
from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.llm import (
    LLMClient,
    LLMClientError,
    LLMRetryExhaustedError,
    StructuredOutputError,
)
from deepresearch_agent.schemas import Evidence, ExtractedClaim, ExtractedClaims, Source, SubQuestion
from deepresearch_agent.security import detect_injection, wrap_untrusted
from deepresearch_agent.settings import project_root

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
NUMBER_RE = re.compile(r"(\$?\d+(?:\.\d+)?%?|\d+(?:\.\d+)?)")
PDF_PAGE_MARKER_RE = re.compile(r"\[\[PDF_PAGE=(\d+)\]\]")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
# R073 bounded one request at 12,000 characters because one request carried
# every source. R093 made each request carry a single source, so the per-source
# bound below is what keeps a request small, and the old total only dropped
# sources: R094's first live run offered 12 candidates, admitted 3, and
# extracted 0 claims from them. The run-level bound is now a source count, so
# every candidate gets its own bounded request.
EXTRACTOR_LLM_MAX_SOURCES = 10
_PAGE_MARKER_RE = re.compile(r"(?=\[\[PDF_PAGE=\d+\]\])")


def _page_blocks(content: str) -> list[str]:
    """Split decoder-marked page text into blocks; one block when unmarked."""

    return [block for block in _PAGE_MARKER_RE.split(content) if block.strip()]

#: R109: 4,000 was too small to hold an answer. Measured on one issuer's annual
#: filing, whose selected pages are 32,603 characters: at 4,000 the excerpt
#: carries 3 of the 4 facts the question asks for, at 8,000 still 3, at 12,000
#: all 4, and 16,000 adds nothing. R093 made the extractor issue one source per
#: call, so this bounds a single request rather than the whole retrieved set.
EXTRACTOR_LLM_MAX_SOURCE_CHARS = 12_000


class ExtractorAgent:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        injection_guard_enabled: bool = False,
        domain_pack: TableExtractionDomain | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.injection_guard_enabled = injection_guard_enabled
        self.domain_pack = resolve_domain_capability(
            domain_pack, consumer="ExtractorAgent"
        )
        self.table_extractors = self.domain_pack.table_extractors()
        self.last_stats: dict[str, int | bool | str] = {}

    def extract(self, research_id: str, sub_question: SubQuestion, sources: list[Source]) -> list[Evidence]:
        if not all(isinstance(source, Source) for source in sources):
            raise TypeError("Extractor accepts Source instances, not retrieval candidates")
        sources, admission_stats = self._admit_sources(sub_question, sources)
        if self.llm_client:
            try:
                evidence = self._llm_extract(
                    research_id,
                    sub_question,
                    sources,
                )
                result = self._with_authoritative_backfills(
                    research_id,
                    sub_question,
                    sources,
                    evidence,
                )
                self.last_stats = {**self.last_stats, **admission_stats}
                return result
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                if (
                    isinstance(exc, LLMRetryExhaustedError)
                    and self.llm_client.fail_on_retry_exhaustion
                ):
                    raise
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
        evidence = self._deterministic_extract(
            research_id,
            sub_question,
            sources,
        )
        result = self._with_authoritative_backfills(
            research_id,
            sub_question,
            sources,
            evidence,
        )
        self.last_stats = {**self.last_stats, **admission_stats}
        return result

    def _admit_sources(
        self,
        sub_question: SubQuestion,
        sources: list[Source],
    ) -> tuple[list[Source], dict[str, int]]:
        """Keep untrusted or irrelevant RAG chunks from becoming Evidence.

        RAG candidates are only retrieval hints until this boundary.  The
        lexical overlap check is deliberately confined to RAG sources: web
        sources retain their established extraction behavior, while a chunk
        that cannot even relate to the requested question must not enter a
        reader-facing conclusion.
        """

        query_terms = self._retrieval_terms(
            " ".join([sub_question.question, *sub_question.search_queries])
        )
        admitted: list[Source] = []
        rejected_irrelevant = 0
        rejected_injection = 0
        for source in sources:
            if source.retrieval_ref is None:
                admitted.append(source)
                continue
            if query_terms and not (query_terms & self._retrieval_terms(source.content)):
                rejected_irrelevant += 1
                continue
            if self.injection_guard_enabled and detect_injection(source.content).risk_score >= 0.5:
                rejected_injection += 1
                continue
            admitted.append(source)
        return admitted, {
            "rag_sources_admitted": len(admitted),
            "rag_sources_rejected_irrelevant": rejected_irrelevant,
            "rag_sources_rejected_injection": rejected_injection,
        }

    @staticmethod
    def _retrieval_terms(text: str) -> set[str]:
        terms: set[str] = set()
        for run in _CJK_RUN_RE.findall(text):
            terms.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
            if len(run) == 1:
                terms.add(run)
        terms.update(word.lower() for word in _WORD_RE.findall(text) if len(word) > 1)
        return terms

    def _with_authoritative_backfills(
        self,
        research_id: str,
        sub_question: SubQuestion,
        sources: list[Source],
        evidence: list[Evidence],
    ) -> list[Evidence]:
        rejections: list[object] = []
        backfills = self.table_extractors.authoritative_backfills(
            research_id,
            sub_question,
            sources,
            rejections=rejections,
        )
        self.last_stats = {
            **self.last_stats,
            "authoritative_financial_backfills": len(backfills),
            "authoritative_parse_rejections": [
                {
                    "reason": item.reason,
                    "page": item.page,
                    "matched_text": item.matched_text,
                }
                for item in rejections
            ],
        }
        return self.table_extractors.merge_authoritative_evidence(
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
                        report_period_end=source.report_period_end,
                        source_date_unknown_reason=source.source_date_unknown_reason,
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
                        retrieval_ref=source.retrieval_ref,
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
        prompt_sources, context_stats = self._llm_prompt_sources(
            sources, sub_question=sub_question
        )
        prompt = (project_root() / "prompts" / "extractor.md").read_text(encoding="utf-8")
        # R093: one source per call. A single call over the whole retrieved set
        # made the response scale with the set, and R091/R092 measured the model
        # filling a 4096 and then an 8192 completion cap regardless of what the
        # prompt or the JSON Schema asked for -- the schema reaches the provider
        # as advisory text, not as a constraint. Bounding the input is the only
        # lever that does not depend on the model complying. A failed batch also
        # costs one source's claims now, not the whole extraction.
        claims: list[ExtractedClaim] = []
        batch_failures: list[str] = []
        for prompt_source in prompt_sources:
            try:
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
                                    "sources": [prompt_source],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                )
            except (LLMClientError, StructuredOutputError) as exc:
                if (
                    isinstance(exc, LLMRetryExhaustedError)
                    and self.llm_client.fail_on_retry_exhaustion
                ):
                    raise
                batch_failures.append(type(exc).__name__)
                continue
            if not isinstance(result.parsed, ExtractedClaims):
                raise ValueError("Extractor did not return ExtractedClaims.")
            claims.extend(result.parsed.claims)
        if batch_failures and not claims:
            raise StructuredOutputError(
                f"every extractor batch failed: {', '.join(sorted(set(batch_failures)))}"
            )
        context_stats = {
            **context_stats,
            "llm_extract_calls": len(prompt_sources),
            "llm_extract_batch_failures": len(batch_failures),
        }
        evidence: list[Evidence] = []
        invalid_extract_text = 0
        incomplete_numeric_fields = 0
        for index, claim in enumerate(claims):
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
                    report_period_end=source.report_period_end,
                    source_date_unknown_reason=source.source_date_unknown_reason,
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
                    retrieval_ref=source.retrieval_ref,
                )
            )
        self.last_stats = {
            "fallback": False,
            "invalid_extract_text": invalid_extract_text,
            "incomplete_numeric_fields": incomplete_numeric_fields,
            "claims": len(evidence),
            "repair_attempts": result.repair_attempts,
            **context_stats,
        }
        return evidence

    def _llm_prompt_sources(
        self,
        sources: list[Source],
        *,
        sub_question: SubQuestion | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, int]]:
        """Bound one extractor request without changing the source evidence set.

        The full ``sources`` list remains available for provenance, claim
        validation, deterministic extraction, and authoritative backfills. This
        method only bounds the untrusted text sent in one provider request.
        """

        tier_rank = {"primary": 0, "secondary": 1, "unknown": 2}
        ordered = sorted(
            enumerate(sources),
            key=lambda item: (
                tier_rank[item[1].source_tier],
                -item[1].credibility,
                item[0],
            ),
        )
        used_chars = 0
        prompt_sources: list[dict[str, str]] = []
        for _, source in ordered:
            if len(prompt_sources) >= EXTRACTOR_LLM_MAX_SOURCES:
                break
            excerpt = self._relevant_excerpt(source.content, sub_question)
            if not excerpt:
                continue
            prompt_sources.append(
                {
                    "title": source.title,
                    "url": source.url,
                    "source_type": source.source_type,
                    "published_at": source.published_at.isoformat() if source.published_at else "unknown",
                    "content": (
                        wrap_untrusted(excerpt, source_url=source.url)
                        if self.injection_guard_enabled
                        else excerpt
                    ),
                }
            )
            used_chars += len(excerpt)
        return prompt_sources, {
            "llm_context_source_count": len(prompt_sources),
            "llm_context_omitted_source_count": len(sources) - len(prompt_sources),
            "llm_context_content_chars": used_chars,
        }

    def _relevant_excerpt(
        self,
        content: str,
        sub_question: SubQuestion | None,
    ) -> str:
        """Spend the source budget on the pages that answer the question.

        R109: this took ``content[:EXTRACTOR_LLM_MAX_SOURCE_CHARS]``. The
        disclosure path already selects the pages worth reading -- on one
        measured filing it picked 28 pages, 32,603 characters, holding every
        figure the question asked for. A prefix cut then kept the first 4,000
        characters of that, which in such a document is front matter: the
        definitions section and the issuer's address, telephone and fax. One
        requested figure sat at character 24,267 and never reached the model;
        another missed the window by 113 characters. The extractor then
        reported that the facts were absent from the text it was given, which
        was true, and was the pipeline's own doing.

        The budget is unchanged. What changes is which characters it buys.
        """

        limit = EXTRACTOR_LLM_MAX_SOURCE_CHARS
        if len(content) <= limit:
            return content
        blocks = _page_blocks(content)
        if len(blocks) <= 1:
            return content[:limit]
        terms = self._relevance_terms(sub_question)
        if not terms:
            return content[:limit]
        scored = sorted(
            enumerate(blocks),
            key=lambda item: (
                -sum(term in item[1] for term in terms),
                item[0],
            ),
        )
        chosen: list[int] = []
        used = 0
        for index, block in scored:
            if used + len(block) > limit and chosen:
                continue
            chosen.append(index)
            used += len(block)
            if used >= limit:
                break
        # Reading order, not relevance order: a page's numbers belong under the
        # heading that names their period and unit.
        return "\n".join(blocks[index] for index in sorted(chosen))[:limit]

    def _relevance_terms(self, sub_question: SubQuestion | None) -> tuple[str, ...]:
        if sub_question is None:
            return ()
        terms = {
            metric
            for request in sub_question.structured_data_requests
            for metric in request.metrics
        }
        terms.update(self.domain_pack.primary_source_terms(financial_intent=True))
        return tuple(term for term in terms if term)

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
