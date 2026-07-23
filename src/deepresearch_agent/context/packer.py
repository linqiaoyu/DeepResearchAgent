from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field

from deepresearch_agent.context.tokens import TokenEstimator, build_token_estimator
from deepresearch_agent.schemas import Evidence, StrictModel


class ContextBudget(StrictModel):
    planner_tokens: int = Field(default=200_000, gt=0)
    extractor_tokens: int = Field(default=200_000, gt=0)
    reporter_tokens: int = Field(default=200_000, gt=0)


class ContextWeights(StrictModel):
    credibility: float = Field(default=0.4, ge=0)
    relevance: float = Field(default=0.4, ge=0)
    freshness: float = Field(default=0.2, ge=0)


class DroppedEvidence(StrictModel):
    evidence_id: str
    reason: Literal["duplicate_url", "duplicate_content", "over_budget", "lower_rank"]
    token_estimate: int = Field(ge=0)


class PackResult(StrictModel):
    selected: list[Evidence] = Field(default_factory=list)
    dropped: list[DroppedEvidence] = Field(default_factory=list)
    token_total: int = Field(ge=0)
    budget: int = Field(gt=0)

    def context_event(self, *, node: str) -> dict[str, object]:
        return {
            "node": node,
            "budget": self.budget,
            "selected_count": len(self.selected),
            "dropped_count": len(self.dropped),
            "token_total": self.token_total,
            "dropped": [item.model_dump(mode="json") for item in self.dropped],
        }


def pack_evidence(
    evidence: list[Evidence],
    *,
    topic: str,
    budget: int,
    as_of: date | None = None,
    weights: ContextWeights | None = None,
    estimator: TokenEstimator | None = None,
) -> PackResult:
    if budget <= 0:
        raise ValueError("context budget must be positive")
    weights = weights or ContextWeights()
    estimator = estimator or build_token_estimator()
    reference_date = as_of or date.today()
    unique: list[tuple[int, Evidence]] = []
    dropped: list[DroppedEvidence] = []
    seen_urls: set[str] = set()
    seen_content: set[str] = set()
    token_counts: dict[str, int] = {}

    for index, item in enumerate(evidence):
        tokens = estimator.estimate(_evidence_text(item))
        token_counts[item.id] = tokens
        normalized_url = _normalize_url(item.source_url)
        content_hash = hashlib.sha256(item.extract_text.encode("utf-8")).hexdigest()
        if normalized_url in seen_urls:
            dropped.append(
                DroppedEvidence(
                    evidence_id=item.id,
                    reason="duplicate_url",
                    token_estimate=tokens,
                )
            )
            continue
        if content_hash in seen_content:
            dropped.append(
                DroppedEvidence(
                    evidence_id=item.id,
                    reason="duplicate_content",
                    token_estimate=tokens,
                )
            )
            continue
        seen_urls.add(normalized_url)
        seen_content.add(content_hash)
        unique.append((index, item))

    ranked = sorted(
        unique,
        key=lambda pair: (
            -_score(pair[1], topic, reference_date, weights),
            pair[0],
            pair[1].id,
        ),
    )
    selected: list[Evidence] = []
    token_total = 0
    for _, item in ranked:
        tokens = token_counts[item.id]
        if tokens > budget:
            dropped.append(
                DroppedEvidence(
                    evidence_id=item.id,
                    reason="over_budget",
                    token_estimate=tokens,
                )
            )
            continue
        if token_total + tokens > budget:
            dropped.append(
                DroppedEvidence(
                    evidence_id=item.id,
                    reason="lower_rank",
                    token_estimate=tokens,
                )
            )
            continue
        selected.append(item)
        token_total += tokens
    return PackResult(
        selected=selected,
        dropped=dropped,
        token_total=token_total,
        budget=budget,
    )


def _score(
    item: Evidence,
    topic: str,
    as_of: date,
    weights: ContextWeights,
) -> float:
    credibility = max(item.confidence, 1e-6)
    relevance = max(_relevance(topic, f"{item.claim} {item.extract_text}"), 1e-6)
    age_days = max(0, (as_of - item.source_pub_date).days)
    freshness = max(1 / (1 + age_days / 365), 1e-6)
    return (
        credibility**weights.credibility
        * relevance**weights.relevance
        * freshness**weights.freshness
    )


def _relevance(topic: str, text: str) -> float:
    topic_tokens = _tokens(topic)
    if not topic_tokens:
        return 1.0
    text_tokens = _tokens(text)
    return len(topic_tokens & text_tokens) / len(topic_tokens)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)}


def _normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _evidence_text(item: Evidence) -> str:
    return "\n".join(
        [
            item.source_title,
            item.source_url,
            item.claim,
            item.extract_text,
        ]
    )
