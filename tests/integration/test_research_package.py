from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deepresearch_agent.config_validation import ConfigurationError
from deepresearch_agent.llm import LLMClient


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_research_package.py"
SPEC = spec_from_file_location("run_research_package", SCRIPT)
assert SPEC and SPEC.loader
run_research_package = module_from_spec(SPEC)
SPEC.loader.exec_module(run_research_package)


class ResearchPackageTests(unittest.TestCase):
    def test_fixture_mode_preserves_explicit_structured_provider(self) -> None:
        with patch.dict(
            os.environ,
            {"DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "akshare"},
            clear=True,
        ):
            run_research_package._configure_mode("fixture", as_of="2026-07-28")

            self.assertEqual(os.environ["DEEPRESEARCH_MODE"], "deterministic")
            self.assertEqual(os.environ["DEEPRESEARCH_SEARCH_PROVIDER"], "fixture")
            self.assertEqual(os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"], "akshare")

    def test_fixture_command_produces_complete_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--topic",
                    "AI Agent 在财富管理行业的落地机会研究",
                    "--as-of",
                    "2026-07-09",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env=self._offline_env(),
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("audit_citation_closure=ok", result.stdout)
            self.assertIn(
                "audit_citation_closure: `ok`",
                (output / "report.md").read_text(encoding="utf-8"),
            )
            for relative in (
                "request.json",
                "report.md",
                "structured.json",
                "structured.md",
                "structured.xlsx",
                "research_snapshot.json",
                "audit_bundle/report.json",
                "audit_bundle/evidence.json",
                "audit_bundle/manifest.json",
            ):
                self.assertTrue((output / relative).is_file(), relative)

    def test_live_preflight_lists_all_requirements_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "must-not-exist"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--topic",
                    "live preflight only",
                    "--as-of",
                    "2026-07-09",
                    "--output",
                    str(output),
                    "--mode",
                    "live",
                    "--env-path",
                    str(Path(tmp) / "absent.env"),
                ],
                cwd=ROOT,
                env=self._offline_env(),
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("DEEPSEEK_API_KEY", result.stdout)
            self.assertIn("TAVILY_API_KEY", result.stdout)
            self.assertIn("--allow-paid-api", result.stdout)
            self.assertIn("single-digit CNY", result.stdout)
            self.assertFalse(output.exists())

    def test_rag_arguments_must_be_supplied_as_a_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "must-not-exist"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--topic",
                    "fixture request",
                    "--as-of",
                    "2026-07-09",
                    "--output",
                    str(output),
                    "--rag-database",
                    str(Path(tmp) / "corpus.db"),
                ],
                cwd=ROOT,
                env=self._offline_env(),
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be supplied together", result.stderr)
            self.assertFalse(output.exists())

    def test_live_rag_composition_requires_all_provider_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            database = Path(tmp) / "corpus.db"
            database.touch()
            with self.assertRaisesRegex(ConfigurationError, "DASHSCOPE_API_KEY"):
                run_research_package._build_live_rag_search(
                    database=database,
                    index_version="idx-v1",
                    ledger_path=Path(tmp) / "ledger.jsonl",
                    global_ledger_path=Path(tmp) / "global.jsonl",
                    budget_cny=1.0,
                    retrieval_top_k=50,
                    rerank_top_n=8,
                )

    def test_live_rag_cost_reconciliation_requires_the_service_ledger_identity(self) -> None:
        self.assertIn("rag_ledger_run_id", SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("Live RAG cost reconciliation", SCRIPT.read_text(encoding="utf-8"))

    def test_live_rag_cost_reconciliation_uses_aggregate_total_cost_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_ledger = root / "global.jsonl"
            global_ledger.write_text(
                '{"run_id":"rag-run","cost_cny":0.125,"role":"embedding"}\n',
                encoding="utf-8",
            )
            ledger = LLMClient(
                ledger_path=root / "rag.jsonl",
                global_ledger_path=global_ledger,
                budget_cny=1.0,
                completion_func=lambda **_: {},
            )
            state = SimpleNamespace(research_id="workflow-run", metadata={})
            rag_search = SimpleNamespace(ledger_run_id="rag-run", ledger=ledger)

            report = run_research_package._append_live_rag_cost_reconciliation(
                report="# report\n",
                state=state,
                rag_search=rag_search,
            )

            self.assertIn("workflow research_id: `workflow-run`", report)
            self.assertIn("RAG ledger run_id: `rag-run`", report)
            self.assertIn("RAG total_cost_cny: `0.125`", report)
            self.assertEqual(state.metadata["rag_ledger_run_id"], "rag-run")
            self.assertEqual(state.metadata["rag_cost_summary"]["total_cost_cny"], 0.125)

    def test_audit_citation_closure_is_preserved_in_delivered_report(self) -> None:
        report = run_research_package._append_audit_citation_closure(
            report="# report\n",
            citation_closure="ok",
        )

        self.assertIn("## Audit citation closure", report)
        self.assertIn("audit_citation_closure: `ok`", report)

    def _offline_env(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "TAVILY_API_KEY"}
        }
        env["PYTHONPATH"] = "src"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["STRUCTURED_LOGGING_ENABLED"] = "false"
        return env


if __name__ == "__main__":
    unittest.main()
