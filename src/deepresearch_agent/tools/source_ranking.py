from __future__ import annotations

from urllib.parse import urlsplit

from deepresearch_agent.schemas import AgentDecision, Source, SubQuestion

DISCLOSURE_DOMAIN_SUFFIXES = ("cninfo.com.cn", "sse.com.cn", "szse.cn")
PRIMARY_DOMAIN_SUFFIXES = ("sec.gov", "hkexnews.hk")
SECONDARY_DOMAIN_SUFFIXES = (
    "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "yicai.com", "caixin.com",
    "moomoo.com", "autohome.com.cn", "guokr.com",
)
REGULATOR_DOMAIN_SUFFIXES = (
    "gov.cn", "csrc.gov.cn", "pbc.gov.cn", "stats.gov.cn", "samr.gov.cn",
)
ASSOCIATION_DOMAIN_SUFFIXES = (
    "amac.org.cn", "china-cba.net", "sac.net.cn",
)
OFFICIAL_PATH_MARKERS = (
    "/announcement", "/announcements", "/disclosure", "/investor",
    "/press/", "/upload/", "/uploads/", "/articlefiledir/",
)
CLOUD_STORAGE_SUFFIXES = ("amazonaws.com", "aliyuncs.com", "myqcloud.com")
OFFICIAL_TEXT_MARKERS = ("本公司及董事会全体成员保证", "官方网站", "投资者关系")
SECONDARY_SOURCE_TYPES = ("blog", "news", "social")
TIER_ORDER = {"primary": 0, "unknown": 1, "secondary": 2}


def classify_source_tier(source: Source) -> str:
    """Classify source provenance with category rules, never question-specific hosts."""

    host = urlsplit(source.url).hostname or ""
    host = host.lower().removeprefix("www.")
    path = urlsplit(source.url).path.lower()
    explicit_tier = classify_source_tier_url(source.url)
    if explicit_tier != "unknown":
        return explicit_tier
    if _matches_suffix(host, DISCLOSURE_DOMAIN_SUFFIXES):
        return "primary"
    if _matches_suffix(host, REGULATOR_DOMAIN_SUFFIXES):
        return "primary"
    if _matches_suffix(host, ASSOCIATION_DOMAIN_SUFFIXES):
        return "primary"
    if source.source_type in {"official", "company", "regulator"}:
        return "primary"
    if (
        any(marker in path for marker in OFFICIAL_PATH_MARKERS)
        and not _matches_suffix(host, CLOUD_STORAGE_SUFFIXES)
    ):
        return "primary"
    visible_text = f"{source.title} {source.content[:500]}"
    if any(marker in visible_text for marker in OFFICIAL_TEXT_MARKERS):
        return "primary"
    if source.source_type in SECONDARY_SOURCE_TYPES:
        return "secondary"
    return "unknown"


def classify_source_tier_url(url: str) -> str:
    """Apply the explicit source-governance list to a URL without ranking it."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if _matches_suffix(host, PRIMARY_DOMAIN_SUFFIXES):
        return "primary"
    if _matches_suffix(host, SECONDARY_DOMAIN_SUFFIXES):
        return "secondary"
    return "unknown"


def rerank_sources(sources: list[Source]) -> list[Source]:
    classified = [
        source.model_copy(update={"source_tier": classify_source_tier(source)})
        for source in sources
    ]
    original_order = {source.url: index for index, source in enumerate(classified)}
    return sorted(
        classified,
        key=lambda source: (
            TIER_ORDER[source.source_tier],
            _is_pdf(source.url),
            original_order[source.url],
        ),
    )


def source_rerank_decision(
    sub_question: SubQuestion,
    original: list[Source],
    ranked: list[Source],
    fetched_urls: list[str],
    *,
    fetch_enabled: bool,
) -> AgentDecision:
    skipped = [source.url for source in ranked if source.url not in fetched_urls]
    return AgentDecision(
        decision_type="source_rerank",
        made_by="ResearcherAgent",
        inputs={
            "sub_question_id": sub_question.id,
            "original_order": [source.url for source in original],
            "ranked_order": [source.url for source in ranked],
            "source_tiers": {
                source.url: source.source_tier for source in ranked
            },
            "fetch_order": fetched_urls,
            "fetch_enabled": fetch_enabled,
            "skipped_candidates": skipped,
        },
        criterion=(
            "rank exchange, statutory, regulator, association, and generic "
            "official-publication paths ahead of unknown and secondary sources; "
            "prefer HTML to PDF within the same tier; "
            + (
                "fetch in ranked order until a primary body is hydrated or "
                "candidates/budget are exhausted"
                if fetch_enabled
                else "classification and rerank only because web_fetch was not selected"
            )
        ),
        outcome=(
            f"ranked={len(ranked)} fetched={len(fetched_urls)} "
            f"primary_hit={any(source.source_tier == 'primary' and source.url in fetched_urls for source in ranked)}"
        ),
        alternatives_considered=skipped,
    )


def _matches_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


def _is_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")
