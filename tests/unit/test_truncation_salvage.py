from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.llm.client import LLMClient, salvage_truncated_json
from deepresearch_agent.schemas import MAX_EXTRACTED_CLAIMS, ExtractedClaims


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
        # R098 lowered MAX_EXTRACTED_CLAIMS to keep the schema's worst case
        # inside the extractor's completion cap, so the fixture is built from
        # the bound rather than from a literal that silently exceeded it. The
        # assertion is unchanged: every element that closed before the cut
        # survives, and the incomplete one is dropped.
        whole = json.dumps(
            {"claims": [_claim(i) for i in range(MAX_EXTRACTED_CLAIMS)]},
            ensure_ascii=False,
        )
        truncated = whole[: whole.rindex("}]}") - 20]

        salvaged = salvage_truncated_json(truncated)

        self.assertIsNotNone(salvaged)
        parsed = ExtractedClaims.model_validate_json(salvaged or "")
        self.assertEqual(len(parsed.claims), MAX_EXTRACTED_CLAIMS - 1)
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

    def test_a_reasoning_model_that_wrote_nothing_is_not_filed_as_truncated(
        self,
    ) -> None:
        """R098: two different faults arrive as finish_reason=length.

        The configured model is a reasoning model and ``max_tokens`` bounds
        reasoning plus content together. Both live runs this round recorded
        ``completion_tokens=8192`` with an empty ``content`` and
        ``reasoning_tokens`` equal to the whole budget: the model thought until
        the budget was gone and never began the JSON. Read as "the response was
        too long for the cap", that sends the fix at the schema's size, which
        is what R090 and this round's first patch both did.
        """

        from deepresearch_agent.llm.client import StructuredOutputTruncatedError

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

            def completion(**_: object) -> dict[str, object]:
                return {
                    "choices": [
                        {"message": {"content": ""}, "finish_reason": "length"}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 8192,
                        "total_tokens": 8202,
                        "completion_tokens_details": {"reasoning_tokens": 8192},
                    },
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env,
            )

            with self.assertRaises(StructuredOutputTruncatedError):
                client.complete(
                    role="reporter",
                    run_id="thinking",
                    schema=ExtractedClaims,
                    messages=[{"role": "user", "content": "report"}],
                )

            row = json.loads(
                (Path(tmp) / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(row["parse_error_kind"], "reasoning_exhausted")
            self.assertEqual(row["reasoning_tokens"], 8192)
            self.assertEqual(row["content_chars"], 0)

            # R099 gave this role a recovery attempt, so a provider that
            # exhausts unconditionally now exhausts twice before the call
            # surfaces. Both are charged and both are recorded; the assertion is
            # raised from 1 to 2 because the behaviour genuinely changed, not to
            # accommodate the new code -- an unrecorded second paid call is
            # exactly what this row exists to prevent.
            health = client.aggregate_run("thinking")["structured_output"]
            self.assertEqual(health["reasoning_exhausted_calls"], 2)
            self.assertEqual(health["reasoning_recovered_calls"], 0)

    def test_an_exhausted_call_is_retried_with_reasoning_disabled(self) -> None:
        """R099: the empty response is recoverable, and only one lever recovers it.

        Measured against the live endpoint at a cap the baseline exhausts
        (`_collab/099/evidence/probe_exhaustion_fix.log`): the same request that
        returns 0 content characters and 400/400 reasoning tokens returns 1581
        content characters and 0 reasoning tokens once the request carries
        ``extra_body={"thinking": {"type": "disabled"}}``. ``reasoning_effort``
        is forwarded and ignored by this endpoint, so the retry has to carry the
        spelling that was measured to work.
        """

        seen: list[object] = []
        whole = json.dumps({"claims": [_claim(0)]}, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

            def completion(**kwargs: object) -> dict[str, object]:
                extra_body = kwargs.get("extra_body")
                seen.append(extra_body)
                if not extra_body:
                    return {
                        "choices": [
                            {"message": {"content": ""}, "finish_reason": "length"}
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 8192,
                            "total_tokens": 8202,
                            "completion_tokens_details": {"reasoning_tokens": 8192},
                        },
                    }
                return {
                    "choices": [
                        {"message": {"content": whole}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 120,
                        "total_tokens": 130,
                        "completion_tokens_details": {"reasoning_tokens": 0},
                    },
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env,
            )

            result = client.complete(
                role="reporter",
                run_id="recovered",
                schema=ExtractedClaims,
                messages=[{"role": "user", "content": "report"}],
            )

            assert isinstance(result.parsed, ExtractedClaims)
            self.assertEqual(len(result.parsed.claims), 1)
            self.assertEqual(seen[0], None)
            self.assertEqual(seen[1], {"thinking": {"type": "disabled"}})

            rows = [
                json.loads(line)
                for line in (Path(tmp) / "ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(rows), 2, "the exhausted call went unrecorded")
            self.assertEqual(rows[0]["parse_error_kind"], "reasoning_exhausted")
            self.assertFalse(rows[0]["reasoning_recovered"])
            self.assertTrue(rows[1]["reasoning_recovered"])

            health = client.aggregate_run("recovered")["structured_output"]
            self.assertEqual(health["reasoning_exhausted_calls"], 1)
            self.assertEqual(health["reasoning_recovered_calls"], 1)

    def test_a_role_with_no_measured_control_is_not_sent_a_guessed_body(self) -> None:
        """R099: the DashScope roles were never probed, so they get no retry.

        Sending them a body measured against a different provider would be a
        guess wearing a measurement's clothes, and a silently ignored parameter
        would read in the ledger as a recovery that worked.
        """

        seen: list[object] = []

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("DASHSCOPE_API_KEY=test-key\n", encoding="utf-8")

            def completion(**kwargs: object) -> dict[str, object]:
                seen.append(kwargs.get("extra_body"))
                return {
                    "choices": [
                        {"message": {"content": ""}, "finish_reason": "length"}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 8192,
                        "total_tokens": 8202,
                        "completion_tokens_details": {"reasoning_tokens": 8192},
                    },
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env,
            )

            from deepresearch_agent.llm.client import StructuredOutputTruncatedError

            with self.assertRaises(StructuredOutputTruncatedError):
                client.complete(
                    role="judge",
                    run_id="unprobed",
                    schema=ExtractedClaims,
                    messages=[{"role": "user", "content": "judge"}],
                )

            self.assertEqual(seen, [None], "an unprobed role was sent a guessed body")

    def test_an_unsalvageable_truncation_keeps_the_payload_that_overran(self) -> None:
        """R098: token counts alone cannot say where the model spent the cap.

        R097's reporter truncation had to be reasoned about from
        `completion_tokens=8192` because the response itself was discarded.
        """

        from deepresearch_agent.llm.client import StructuredOutputTruncatedError

        content = '{"claims": [{"claim": "half'
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, content, completion_tokens=8192)

            with self.assertRaises(StructuredOutputTruncatedError):
                client.complete(
                    role="extractor",
                    run_id="dumped",
                    schema=ExtractedClaims,
                    messages=[{"role": "user", "content": "extract"}],
                )

            dump = Path(tmp) / "truncated_payloads" / "dumped.extractor.json"
            self.assertTrue(dump.exists(), "the overrunning payload was discarded")
            self.assertIn("half", dump.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
