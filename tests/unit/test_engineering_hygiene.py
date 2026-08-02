from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow.engine import _strategy_config


class EngineeringHygieneTests(unittest.TestCase):
    def test_finance_pack_import_is_lazy_and_missing_assets_fail_at_retrieval(self) -> None:
        pack_module = importlib.import_module("deepresearch_agent.domains.finance.pack")
        aliases_module = importlib.import_module("deepresearch_agent.domains.finance.issuer_aliases")
        aliases_module._assets.cache_clear()
        aliases_module.issuer_aliases.cache_clear()
        with tempfile.TemporaryDirectory() as tmp, patch.object(aliases_module, "project_root", return_value=Path(tmp)):
            reloaded = importlib.reload(pack_module)
            self.assertTrue(hasattr(reloaded, "FinanceDomainPack"))
            with self.assertRaisesRegex(ValueError, "finance_sec_issuer_catalog_v1.json"):
                reloaded.FinanceDomainPack().retrieval_filter_values("阿里巴巴 2024 年")
        aliases_module._assets.cache_clear()
        aliases_module.issuer_aliases.cache_clear()
        importlib.reload(pack_module)

    def test_strategy_config_includes_all_boolean_settings_and_retrieval_controls(self) -> None:
        settings = replace(
            Settings(storage_path=Path("/tmp/strategy.db")),
            rerank_enabled=False,
            rerank_fail_open=False,
            trajectory_record_enabled=True,
            retrieval_top_k=21,
            rerank_top_n=6,
        )
        strategy = _strategy_config(settings, rag_index_version="idx-v1")
        self.assertFalse(strategy["rerank_enabled"])
        self.assertFalse(strategy["rerank_fail_open"])
        self.assertTrue(strategy["trajectory_record_enabled"])
        self.assertEqual(strategy["retrieval_top_k"], 21)
        self.assertEqual(strategy["rerank_top_n"], 6)
        self.assertEqual(strategy["rag_index_version"], "idx-v1")

    def test_every_public_lazy_export_resolves(self) -> None:
        import deepresearch_agent
        import deepresearch_agent.rag as rag
        import deepresearch_agent.tools as tools

        self.assertEqual(deepresearch_agent.__all__, ["DeepResearchEngine"])
        self.assertEqual(rag.__all__, ["ingest_corpus"])
        self.assertGreater(len(tools.__all__), 1)
        for module in (deepresearch_agent, tools, rag):
            for name in module.__all__:
                self.assertIsNotNone(getattr(module, name), f"{module.__name__}.{name}")

    def test_rag_budget_uses_the_prefixed_environment_variable(self) -> None:
        from deepresearch_agent.settings import load_settings

        with patch.dict(os.environ, {"DEEPRESEARCH_RAG_BUDGET_CNY": "7.5"}, clear=True):
            self.assertEqual(load_settings().rag_budget_cny, 7.5)

    def test_gate_subprocesses_receive_devnull_stdin(self) -> None:
        from importlib.util import module_from_spec, spec_from_file_location

        root = Path(__file__).resolve().parents[2]
        spec = spec_from_file_location("gate", root / "scripts" / "gate.py")
        assert spec and spec.loader
        gate = module_from_spec(spec)
        spec.loader.exec_module(gate)
        with patch.object(gate.subprocess, "run") as run:
            run.return_value.returncode = 0
            gate._run("probe", ["python", "-c", "pass"], {})
            gate._tracked_diff()
        self.assertEqual(run.call_args_list[0].kwargs["stdin"], gate.subprocess.DEVNULL)
        self.assertEqual(run.call_args_list[1].kwargs["stdin"], gate.subprocess.DEVNULL)
