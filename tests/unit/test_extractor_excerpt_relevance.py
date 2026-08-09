"""R109: the extractor's budget must buy the pages that answer the question.

Measured on a real A-share annual filing during R109. The disclosure path
selected 28 pages -- 32,603 characters holding every figure the question asked
for -- and the extractor then took `content[:4000]`. In such a document the
first 4,000 characters are front matter: a definitions section and the issuer's
address, telephone and fax. One requested figure sat at character 24,267 and
never reached the model; another missed the window by 113 characters. The
extractor reported the facts absent from the text it was given, which was true
and was the pipeline's own doing. The golden-set case built from that filing
scored 0.165 fact coverage.

The page blocks below reproduce that shape: boilerplate first, the answer late.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.agents.extractor import (
    EXTRACTOR_LLM_MAX_SOURCE_CHARS,
    ExtractorAgent,
)
from deepresearch_agent.schemas import Source, StructuredDataRequest, SubQuestion

FILLER = "本公司注册地址、办公地址、电话、传真与电子信箱等联系方式。" * 60
ANSWER = "营业总收入 174,144,069,958.24 元，归属于母公司股东的净利润 86,228,146,421.62 元。"


def _page(number: int, body: str) -> str:
    return f"[[PDF_PAGE={number}]]\n{body}"


class ExtractorExcerptRelevanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = ExtractorAgent()
        self.sub_question = SubQuestion(
            id="overall",
            question="解读该公司 2024 年度业绩",
            search_queries=["年度报告"],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    symbol="600519",
                    periods=["20241231"],
                    metrics=["营业总收入"],
                )
            ],
        )
        # Front matter first, the answer on a late page -- a filing's real order.
        self.content = "\n".join(
            [_page(index, FILLER) for index in range(1, 12)]
            + [_page(12, f"合并利润表\n{ANSWER}")]
            + [_page(index, FILLER) for index in range(13, 20)]
        )

    def test_the_answer_page_reaches_the_model(self) -> None:
        excerpt = self.extractor._relevant_excerpt(self.content, self.sub_question)

        self.assertIn("174,144,069,958.24", excerpt)

    def test_a_prefix_of_the_same_budget_would_not_have(self) -> None:
        """The failure this guard exists for, stated as a measurement."""
        self.assertGreater(len(self.content), EXTRACTOR_LLM_MAX_SOURCE_CHARS)
        self.assertNotIn(
            "174,144,069,958.24",
            self.content[:EXTRACTOR_LLM_MAX_SOURCE_CHARS],
        )

    def test_the_budget_is_still_enforced(self) -> None:
        excerpt = self.extractor._relevant_excerpt(self.content, self.sub_question)

        self.assertLessEqual(len(excerpt), EXTRACTOR_LLM_MAX_SOURCE_CHARS)

    def test_pages_keep_reading_order(self) -> None:
        """A figure belongs under the heading naming its period and unit."""
        content = "\n".join(
            [_page(1, FILLER), _page(2, f"合并利润表\n{ANSWER}"), _page(3, "营业总收入 说明")]
        )

        excerpt = self.extractor._relevant_excerpt(content, self.sub_question)

        self.assertLess(excerpt.index("[[PDF_PAGE=2]]"), excerpt.index("[[PDF_PAGE=3]]"))

    def test_short_sources_are_untouched(self) -> None:
        short = "营业总收入 1,000 元"

        self.assertEqual(
            self.extractor._relevant_excerpt(short, self.sub_question), short
        )

    def test_the_wiring_uses_the_relevant_excerpt_not_a_prefix(self) -> None:
        """Through `_llm_prompt_sources`, which is what the run actually calls."""
        source = Source(
            title="年度报告",
            url="https://static.cninfo.com.cn/finalpage/600519.PDF",
            source_type="pdf",
            content=self.content,
            source_tier="primary",
        )

        prompt_sources, stats = self.extractor._llm_prompt_sources(
            [source], sub_question=self.sub_question
        )

        self.assertEqual(len(prompt_sources), 1)
        self.assertIn("174,144,069,958.24", prompt_sources[0]["content"])
        self.assertLessEqual(
            stats["llm_context_content_chars"], EXTRACTOR_LLM_MAX_SOURCE_CHARS
        )

    def test_unpaged_sources_fall_back_to_the_prefix(self) -> None:
        """A web page has no page markers; the budget still applies."""
        plain = FILLER * 20

        excerpt = self.extractor._relevant_excerpt(plain, self.sub_question)

        self.assertEqual(excerpt, plain[:EXTRACTOR_LLM_MAX_SOURCE_CHARS])


if __name__ == "__main__":
    unittest.main()
