from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.llm.client import LLMClient, salvage_truncated_json
from deepresearch_agent.schemas import ExtractedClaims


def _claim(index: int) -> dict[str, object]:
    return {
        "claim": f"claim {index}",
        "claim_type": "fact",
        "source_url": "https://example.test",
        "extract_text": f"extract {index}",
    }


class SalvageTruncatedJsonTests(unittest.TestCase):
    """R093: a response cut off mid-element keeps the elements before the cut."""

    def test_complete_elements_survive_the_cut(self) -> None:
        whole = json.dumps({"claims": [_claim(i) for i in range(11)]}, ensure_ascii=False)
        truncated = whole[: whole.rindex("}]}") - 20]

        salvaged = salvage_truncated_json(truncated)

        self.assertIsNotNone(salvaged)
        parsed = ExtractedClaims.model_validate_json(salvaged or "")
        self.assertEqual(len(parsed.claims), 10)
        self.assertEqual(parsed.claims[0].claim, "claim 0")

    def test_a_complete_document_is_not_touched(self) -> None:
        whole = json.dumps({"claims": [_claim(0)]}, ensure_ascii=False)

        self.assertIsNone(salvage_truncated_json(whole))

    def test_a_cut_before_any_complete_element_yields_nothing(self) -> None:
        self.assertIsNone(salvage_truncated_json('{"claims": [{"claim": "half'))

    def test_brackets_inside_strings_do_not_confuse_the_scan(self) -> None:
        text = '{"claims": [{"claim": "a]}b", "claim_type": "fact", "source_url": "u", "extract_text": "e"}, {"claim": "x'

        salvaged = salvage_truncated_json(text)

        self.assertIsNotNone(salvaged)
        self.assertEqual(json.loads(salvaged or "")["claims"][0]["claim"], "a]}b")


class ClientSalvageTests(unittest.TestCase):
    def _client(self, tmp: str, content: str, completion_tokens: int) -> LLMClient:
        env = Path(tmp) / ".env"
        env.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

        def completion(**_: object) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": content}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": completion_tokens,
                    "total_tokens": 10 + completion_tokens,
                },
            }

        return LLMClient(
            ledger_path=Path(tmp) / "ledger.jsonl",
            global_ledger_path=Path(tmp) / "global.jsonl",
            budget_cny=3.0,
            completion_func=completion,
            sleep_func=lambda _: None,
            env_path=env,
        )

    def test_a_truncated_response_yields_its_complete_claims(self) -> None:
        whole = json.dumps({"claims": [_claim(i) for i in range(5)]}, ensure_ascii=False)
        truncated = whole[: whole.rindex("}]}") - 20]
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, truncated, completion_tokens=8192)

            result = client.complete(
                role="extractor",
                run_id="salvage",
                schema=ExtractedClaims,
                messages=[{"role": "user", "content": "extract"}],
            )

            assert isinstance(result.parsed, ExtractedClaims)
            self.assertEqual(len(result.parsed.claims), 4)
            row = json.loads(
                (Path(tmp) / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertTrue(row["truncated"])
            self.assertTrue(row["salvaged"])
            health = client.aggregate_run("salvage")["structured_output"]
            self.assertEqual(health["truncated_calls"], 1)
            self.assertEqual(health["salvaged_calls"], 1)

    def test_a_truncation_with_nothing_complete_still_raises(self) -> None:
        from deepresearch_agent.llm.client import StructuredOutputTruncatedError

        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, '{"claims": [{"claim": "half', completion_tokens=8192)

            with self.assertRaises(StructuredOutputTruncatedError):
                client.complete(
                    role="extractor",
                    run_id="unsalvageable",
                    schema=ExtractedClaims,
                    messages=[{"role": "user", "content": "extract"}],
                )


if __name__ == "__main__":
    unittest.main()
