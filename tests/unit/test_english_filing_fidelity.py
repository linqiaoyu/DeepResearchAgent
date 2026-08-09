"""R104: an analysis line quoting an English filing must survive the guard."""

from __future__ import annotations

import unittest

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import Evidence

FINANCE = load_domain_pack("finance")
REQUIRED = {"营业收入", "主营业务毛利率"}

# Verbatim extracts from the NIO 20-F that R103's live run retrieved and whose
# analysis lines the guard then deleted.
FILING_MARGIN = "Gross margin in 2023 was 5.5%, compared with 10.4% in 2022."
FILING_MARGIN_2024 = (
    "The increase of gross margin as compared to 2023 was mainly driven by the "
    "increase of vehicle margin to 9.9% in 2024."
)
FILING_QUARTER = (
    "Gross margin was 4.9% in the first quarter of 2024, compared with 1.5% in "
    "the first quarter of 2023 and 7.5% in the fourth quarter of 2023."
)
FILING_REVENUE = (
    "Total revenues were RMB9,908.6 million (US$1,372.3 million) in the first "
    "quarter of 2024."
)


def _evidence(*texts: str) -> list[Evidence]:
    return [
        Evidence(
            id=f"e{index}",
            research_id="r",
            sub_question_id="s",
            claim=text,
            claim_type="fact",
            source_url="https://www.sec.gov/Archives/edgar/data/1736541/nio-20241231x20f.htm",
            source_title="nio-20241231x20f.htm",
            extract_text=text,
            source_tier="primary",
        )
        for index, text in enumerate(texts)
    ]


class EnglishFilingFidelityTests(unittest.TestCase):
    """The better the source, the more analysis was deleted.

    Every figure in an English 20-F was invisible to the numeric guard, whose
    patterns were Chinese-only. A reporter that faithfully translated and
    converted a filing sentence had that line replaced by
    `该数值表述未通过 Evidence 保真守卫` -- four of the five analysis lines in
    R103's live run, all citing primary filings.
    """

    def _rejected(self, claim: str, *evidence: str) -> bool:
        return FINANCE.numeric_citation_policy().has_numeric_mismatch(
            claim, _evidence(*evidence), required_metrics=REQUIRED
        )

    def test_a_margin_line_quoting_the_filing_is_supported(self) -> None:
        self.assertFalse(
            self._rejected(
                "2023年毛利率5.5%，低于2022年的10.4%；2024年毛利率提升至9.9%。",
                FILING_MARGIN,
                FILING_MARGIN_2024,
            )
        )

    def test_the_year_is_read_from_after_the_figure_as_english_writes_it(self) -> None:
        """`was 4.9% in ... 2024, compared with 1.5% in ... 2023` binds each to its own year."""

        self.assertFalse(
            self._rejected(
                "2024年第一季度毛利率为4.9%，高于2023年同期的1.5%，"
                "但低于2023年第四季度的7.5%。",
                FILING_QUARTER,
            )
        )

    def test_an_rmb_scale_amount_supports_a_converted_claim(self) -> None:
        """RMB9,908.6 million is 99.09亿元, and the reader is owed that line."""

        self.assertFalse(
            self._rejected("2024年第一季度总营收99.09亿元。", FILING_REVENUE)
        )

    def test_a_dollar_figure_never_supports_a_yuan_claim(self) -> None:
        """A 20-F prints both currencies side by side; only one is CNY."""

        self.assertTrue(
            self._rejected(
                "2024年第一季度总营收13.72亿元。",
                "Total revenues were US$1,372.3 million in the first quarter of 2024.",
            )
        )

    def test_an_unqualified_scale_is_not_taken_as_yuan(self) -> None:
        self.assertTrue(
            self._rejected(
                "2024年第一季度总营收99.09亿元。",
                "Total revenues were 9,908.6 million in the first quarter of 2024.",
            )
        )

    def test_a_fabricated_figure_is_still_rejected(self) -> None:
        self.assertTrue(
            self._rejected("2024年第一季度总营收150.00亿元。", FILING_REVENUE)
        )

    def test_the_wrong_year_is_still_rejected(self) -> None:
        self.assertTrue(self._rejected("2024年毛利率5.5%。", FILING_MARGIN))

    def test_a_fabricated_margin_is_still_rejected(self) -> None:
        self.assertTrue(self._rejected("2023年毛利率8.8%。", FILING_MARGIN))


if __name__ == "__main__":
    unittest.main()
