from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_llm_agent_liveness import (
    check_package,
    measure_package,
    reference_extractor_payload,
    reference_reporter_payload,
    self_test,
)

from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG


HEALTHY_REPORT = """# 报告

## 关键发现
- 结论一。 [^1]

## 详细分析
### 子问题
- 分析一，解释支持与限制。 [^1]
- 分析二，说明口径差异。 [^2]

## 参考来源
[^1]: source one. https://one.example (2025-04-08)
[^2]: source two. https://two.example (2025-04-08)
"""


def _package(
    root: Path,
    ledger: dict[str, object],
    report: str = HEALTHY_REPORT,
) -> Path:
    package = root / "package"
    (package / "audit_bundle").mkdir(parents=True)
    (package / "audit_bundle" / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )
    (package / "report.md").write_text(report, encoding="utf-8")
    return package


def _healthy_ledger() -> dict[str, object]:
    return {
        "mode": "llm",
        "structured_output": {
            "structured_calls": 4,
            "structured_parse_errors": 0,
            "truncated_calls": 0,
        },
        "llm_stats": {
            "extractor": [{"fallback": False, "sub_question_id": "rev"}],
            "reporter": {
                "fallback": False,
                "claim_provenance": [
                    {
                        "path": f"key_findings:{index}",
                        "provenance": "first_pass",
                        "has_citation": True,
                        "invalid_reference_count": 0,
                    }
                    for index in range(3)
                ],
            },
        },
    }


class LlmAgentLivenessPackageTests(unittest.TestCase):
    def test_a_healthy_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), _healthy_ledger())

            self.assertEqual(
                check_package(package, min_authored_claims=3, llm_ledger=None), 0
            )

    def test_extractor_fallback_fails(self) -> None:
        ledger = _healthy_ledger()
        ledger["llm_stats"]["extractor"][0]["fallback"] = True  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), ledger)

            self.assertEqual(
                check_package(package, min_authored_claims=3, llm_ledger=None), 1
            )

    def test_reporter_fallback_fails(self) -> None:
        ledger = _healthy_ledger()
        ledger["llm_stats"]["reporter"]["fallback"] = True  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), ledger)

            self.assertEqual(
                check_package(package, min_authored_claims=3, llm_ledger=None), 1
            )

    def test_truncated_structured_call_fails(self) -> None:
        ledger = _healthy_ledger()
        ledger["structured_output"]["truncated_calls"] = 1  # type: ignore[index]
        ledger["structured_output"]["structured_parse_errors"] = 1  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), ledger)

            self.assertEqual(
                check_package(package, min_authored_claims=3, llm_ledger=None), 1
            )

    def test_mechanically_assembled_findings_do_not_count_as_authored(self) -> None:
        """The R087 deliverable's exact shape: cited, closed, and LLM-free."""

        ledger = _healthy_ledger()
        for entry in ledger["llm_stats"]["reporter"]["claim_provenance"]:  # type: ignore[index]
            entry["provenance"] = "mechanical_grounded_fact"
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), ledger)

            measurement = measure_package(package)

            self.assertEqual(measurement.llm_authored_claims, 0)
            self.assertEqual(
                check_package(package, min_authored_claims=3, llm_ledger=None), 1
            )

    def test_uncited_authored_claims_do_not_count(self) -> None:
        ledger = _healthy_ledger()
        entries = ledger["llm_stats"]["reporter"]["claim_provenance"]  # type: ignore[index]
        entries[0]["has_citation"] = False
        entries[1]["invalid_reference_count"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), ledger)

            self.assertEqual(measure_package(package).llm_authored_claims, 1)

    def test_authored_claims_that_never_reach_the_reader_still_fail(self) -> None:
        """The R087 shape: the pipeline records analysis, compaction deletes it.

        Without this, a package could report `llm_authored_claims=9` while the
        delivered report shows the reader two mechanical numbers.
        """

        report = HEALTHY_REPORT.replace(
            "## 详细分析\n### 子问题\n- 分析一，解释支持与限制。 [^1]\n- 分析二，说明口径差异。 [^2]\n",
            "",
        )
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), _healthy_ledger(), report=report)

            measurement = measure_package(package)

            self.assertEqual(measurement.llm_authored_claims, 3)
            self.assertEqual(measurement.reader_analysis_lines, 0)
            self.assertEqual(
                check_package(package, min_authored_claims=3, llm_ledger=None), 1
            )

    def test_uncited_analysis_lines_do_not_count(self) -> None:
        report = HEALTHY_REPORT.replace("- 分析二，说明口径差异。 [^2]", "- 分析二，无出处。")
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), _healthy_ledger(), report=report)

            self.assertEqual(measure_package(package).reader_analysis_lines, 1)

    def test_footnotes_listed_but_never_cited_are_counted(self) -> None:
        report = HEALTHY_REPORT + "[^3]: source three. https://three.example (2025-04-08)\n"
        with tempfile.TemporaryDirectory() as tmp:
            package = _package(Path(tmp), _healthy_ledger(), report=report)

            self.assertEqual(measure_package(package).orphan_footnotes, 1)

    def test_pre_r090_package_reconstructs_health_from_the_global_ledger(self) -> None:
        ledger = _healthy_ledger()
        del ledger["structured_output"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = _package(root, ledger)
            (package / "runs" / "run-1").mkdir(parents=True)
            (package / "runs" / "run-1" / "manifest.json").write_text(
                json.dumps({"run_id": "run-1"}), encoding="utf-8"
            )
            global_ledger = root / "llm_ledger.jsonl"
            global_ledger.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {"run_id": "run-1", "structured": True, "parse_error": True,
                         "truncated": True},
                        {"run_id": "run-1", "structured": True, "parse_error": False,
                         "truncated": False},
                        {"run_id": "other", "structured": True, "parse_error": True,
                         "truncated": True},
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            measurement = measure_package(package, llm_ledger=global_ledger)

            self.assertEqual(measurement.structured_parse_errors, 1)
            self.assertEqual(measurement.truncated_calls, 1)


class LlmAgentLivenessSelfTestTests(unittest.TestCase):
    def test_current_role_caps_carry_their_own_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self_test(Path(tmp)), 0)

    def test_reference_payloads_exceed_the_retired_1024_token_cap(self) -> None:
        """The guard must reject the exact configuration that broke R073-R089.

        Both references stay below what the R087 reporter was already emitting
        when the cap cut it off, so this is a floor, not a padded target.
        """

        from scripts.check_llm_agent_liveness import _estimate_tokens

        for payload in (reference_extractor_payload(), reference_reporter_payload()):
            self.assertGreater(_estimate_tokens(payload), 1024)

    def test_role_caps_stay_above_their_reference_responses(self) -> None:
        from scripts.check_llm_agent_liveness import _estimate_tokens

        for role, payload in (
            ("extractor", reference_extractor_payload()),
            ("reporter", reference_reporter_payload()),
        ):
            with self.subTest(role=role):
                self.assertGreater(
                    DEFAULT_LLM_CONFIG.roles[role].max_completion_tokens,
                    _estimate_tokens(payload),
                )

    def test_cli_reports_a_missing_package_without_an_import_error(self) -> None:
        root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [sys.executable, "scripts/check_llm_agent_liveness.py", "--self-test"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("self_test_failures=0", completed.stdout)
        self.assertNotIn("ModuleNotFoundError", completed.stderr)


if __name__ == "__main__":
    unittest.main()
