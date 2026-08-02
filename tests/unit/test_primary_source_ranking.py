from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import ExtractorAgent, ReporterAgent, ResearcherAgent
from deepresearch_agent.schemas import ResearchPlan, ResearchState, Source, SubQuestion
from deepresearch_agent.tools.source_ranking import (
    classify_source_tier,
    rerank_sources,
)


def source(
    url: str,
    *,
    source_type: str = "web",
    content: str = "这是一段超过三十个字符的候选摘要，用于验证来源分级会进入下游证据对象。",
) -> Source:
    return Source(
        id=url,
        title=url,
        url=url,
        source_type=source_type,
        published_at=date(2026, 7, 25),
        content=content,
    )


class CandidateProvider:
    search_counts_toward_budget = True

    def __init__(self, candidates: list[Source]) -> None:
        self.candidates = candidates
        self.fetch_order: list[str] = []

    def search(
        self,
        query: str,
        top_k: int = 3,
        source_type: str | None = None,
        **_kwargs: object,
    ) -> list[Source]:
        return self.candidates[:top_k]

    def fetch(self, url: str, **_kwargs: object) -> Source:
        self.fetch_order.append(url)
        return source(
            url,
            source_type="web_fetch",
            content="宁德时代公告正文显示项目已获审议通过，规划产能为 100 GWh。",
        )


class PrimarySourceRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secondary = source(
            "https://media.example/story",
            source_type="news",
        )
        self.unknown = source("https://research.example/article")
        self.primary_pdf = source(
            "https://issuer.example/uploads/disclosure.pdf"
        )
        self.primary_html = source(
            "https://issuer.example/investor/news/disclosure"
        )

    def test_category_rules_cover_disclosure_regulator_association_and_company(self) -> None:
        urls = [
            "https://static.cninfo.com.cn/finalpage/report.pdf",
            "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
            "https://agency.gov.cn/press/release.html",
            "https://www.amac.org.cn/news/notice.html",
            "https://issuer.example/articleFileDir/report.pdf",
        ]
        self.assertTrue(
            all(classify_source_tier(source(url)) == "primary" for url in urls)
        )
        self.assertEqual(classify_source_tier(self.secondary), "secondary")
        self.assertEqual(classify_source_tier(self.unknown), "unknown")

    def test_explicit_sec_and_news_domains_are_classified(self) -> None:
        self.assertEqual(classify_source_tier(source("https://www.sec.gov/Archives/edgar/data/1/x.htm")), "primary")
        self.assertEqual(classify_source_tier(source("https://www.reuters.com/world/story", source_type="web")), "secondary")

    def test_primary_html_ranks_before_primary_pdf_and_other_tiers(self) -> None:
        ranked = rerank_sources(
            [
                self.secondary,
                self.unknown,
                self.primary_pdf,
                self.primary_html,
            ]
        )
        self.assertEqual(
            [item.url for item in ranked],
            [
                self.primary_html.url,
                self.primary_pdf.url,
                self.unknown.url,
                self.secondary.url,
            ],
        )

    def test_fetch_order_matches_rerank_and_stops_after_primary_body(self) -> None:
        provider = CandidateProvider(
            [self.secondary, self.primary_pdf, self.primary_html, self.unknown]
        )
        researcher = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            max_searches_per_run=10,
        )
        sources, records, calls, exhausted, decisions = researcher.research_with_budget(
            SubQuestion(id="q1", question="公告", search_queries=["query"]),
            max_search_calls=5,
            enable_web_fetch=True,
        )
        self.assertEqual(provider.fetch_order, [self.primary_html.url])
        self.assertEqual(calls, 2)
        self.assertFalse(exhausted)
        self.assertEqual(sources[0].source_tier, "primary")
        self.assertEqual(records[-1].query, f"[web_fetch] {self.primary_html.url}")
        self.assertEqual(
            decisions[0].inputs["ranked_order"][0],
            self.primary_html.url,
        )
        self.assertIn(self.primary_pdf.url, decisions[0].alternatives_considered)

    def test_fetch_stops_when_branch_budget_is_exhausted(self) -> None:
        provider = CandidateProvider([self.primary_html])
        researcher = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            max_searches_per_run=10,
        )
        _sources, records, calls, exhausted, _decisions = researcher.research_with_budget(
            SubQuestion(id="q1", question="公告", search_queries=["query"]),
            max_search_calls=1,
            enable_web_fetch=True,
        )
        self.assertEqual(provider.fetch_order, [])
        self.assertEqual(calls, 1)
        self.assertTrue(exhausted)
        self.assertTrue(records[-1].query.startswith("[fetch_budget_exceeded]"))

    def test_rule_assigned_tier_flows_from_source_into_evidence(self) -> None:
        provider = CandidateProvider([self.primary_html])
        researcher = ResearcherAgent(search_tool=provider, fetch_tool=provider)
        sub_question = SubQuestion(id="q1", question="公告", search_queries=["query"])
        sources, _records, _calls, _exhausted, _decisions = (
            researcher.research_with_budget(
                sub_question,
                max_search_calls=3,
                enable_web_fetch=True,
            )
        )
        evidence = ExtractorAgent().extract("tier-run", sub_question, sources)
        self.assertTrue(evidence)
        self.assertIn("primary", {item.source_tier for item in evidence})
        self.assertTrue(
            all(
                item.source_tier in {"primary", "secondary", "unknown"}
                for item in evidence
            )
        )

    def test_report_reference_section_exposes_every_evidence_tier(self) -> None:
        sub_question = SubQuestion(id="q1", question="公告", search_queries=[])
        evidence = ExtractorAgent().extract(
            "tier-report",
            sub_question,
            [rerank_sources([self.primary_html])[0], self.unknown],
        )
        state = ResearchState(
            research_id="tier-report",
            topic="来源分级",
            plan=ResearchPlan(topic="来源分级", sub_questions=[sub_question]),
            evidence_store=evidence,
        )
        report = ReporterAgent().report(state)
        references = report.split("## 参考来源", 1)[1]
        self.assertIn("[source_tier=primary]", references)
        self.assertIn("[source_tier=unknown]", references)


if __name__ == "__main__":
    unittest.main()
