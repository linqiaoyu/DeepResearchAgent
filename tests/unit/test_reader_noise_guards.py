from __future__ import annotations

import json
import unittest
from datetime import date

from scripts.check_087_report_shape import measure

from deepresearch_agent.agents.critic import CriticAgent
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.llm.client import salvage_truncated_json
from deepresearch_agent.schemas import Evidence, ReportDraft

FINANCE = load_domain_pack("finance")

HKEX_URL = (
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0321/2025032100789_c.pdf"
)


def _evidence(index: int, url: str = HKEX_URL) -> Evidence:
    return Evidence(
        id=f"e{index}",
        research_id="run",
        sub_question_id="rev",
        claim=f"披露事实 {index}。",
        claim_type="data",
        source_url=url,
        source_title="2025032100789_c.pdf",
        source_pub_date=date(2025, 3, 21),
        extract_text=f"披露事实 {index}。",
    )


class FilingVenueTests(unittest.TestCase):
    """R095: a filing is a filing whatever the repository names the file."""

    def test_an_hkex_pdf_is_recognised_as_an_annual_disclosure(self) -> None:
        self.assertTrue(FINANCE.is_historical_annual_disclosure(_evidence(0)))

    def test_a_stale_warning_about_a_filing_is_hidden_from_the_reader(self) -> None:
        line = (
            "- outdated_source (medium): Source '2025032100789_c.pdf' is 547 days old "
            f"for a time-sensitive claim. {HKEX_URL}"
        )

        self.assertFalse(FINANCE.reader_risk_visible(line))

    def test_a_genuinely_stale_news_source_still_reaches_the_reader(self) -> None:
        line = (
            "- outdated_source (medium): Source 'blog post' is 900 days old for a "
            "time-sensitive claim. https://news.example/post"
        )

        self.assertTrue(FINANCE.reader_risk_visible(line))


class CriticDeduplicationTests(unittest.TestCase):
    def test_one_stale_source_produces_one_issue_not_one_per_claim(self) -> None:
        """R094 delivered the same sentence five times, one per quoting claim."""

        critic = CriticAgent()
        critic.today = date(2026, 9, 19)
        evidence = [_evidence(index, url="https://news.example/post") for index in range(5)]

        issues = critic._outdated_sources(evidence)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "outdated_source")


class ReportDraftOrderTests(unittest.TestCase):
    def test_the_analysis_is_emitted_before_the_always_replaced_findings(self) -> None:
        """A cut keeps a prefix, so field order decides what the reader loses."""

        properties = list(ReportDraft.model_json_schema()["properties"])

        self.assertLess(
            properties.index("detailed_analysis"), properties.index("key_findings")
        )
        self.assertLess(
            properties.index("unverified_assumptions"), properties.index("key_findings")
        )

    def test_a_truncated_draft_still_carries_its_analysis(self) -> None:
        draft = {
            "summary": "摘要。",
            "detailed_analysis": [
                {
                    "sub_question_id": "rev",
                    "heading": "营收结构",
                    "claims": [
                        {"text": "分析一。", "evidence_ids": ["e0"]},
                        {"text": "分析二。", "evidence_ids": ["e1"]},
                    ],
                }
            ],
            "risks": ["风险一。"],
            "unverified_assumptions": [{"text": "假设一。", "evidence_ids": ["e0"]}],
            "key_findings": [{"text": "结论一。", "evidence_ids": ["e0"]}],
        }
        whole = json.dumps(draft, ensure_ascii=False)
        truncated = whole[: whole.index('"key_findings"') + 30]

        salvaged = salvage_truncated_json(truncated)

        assert salvaged is not None
        recovered = ReportDraft.model_validate_json(salvaged)
        self.assertEqual(len(recovered.detailed_analysis[0].claims), 2)
        self.assertEqual(len(recovered.unverified_assumptions), 1)


class ReaderNoiseMeasureTests(unittest.TestCase):
    def test_repeated_and_filing_age_risk_lines_count_as_noise(self) -> None:
        """The R094 delivery read `noise_lines=0` while showing five bogus lines."""

        risk = (
            "- outdated_source (medium): Source '2025032100789_c.pdf' is 547 days old "
            "for a time-sensitive claim. Affected: footnote-8."
        )
        report = "# r\n\n## 风险与限制\n" + "\n".join([risk] * 5) + "\n\n## 参考来源\n[^1]: s\n"

        values = measure(report)

        self.assertEqual(values["duplicate_reader_lines"], 4)
        self.assertEqual(values["analysis_false_positives"], 5)
        self.assertGreater(values["noise_lines"], 0)


if __name__ == "__main__":
    unittest.main()
