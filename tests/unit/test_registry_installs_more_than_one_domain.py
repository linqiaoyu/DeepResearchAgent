"""R110: the registry knew exactly one name, so the domain was not swappable.

`load_domain_pack` accepted `"finance"` and raised for everything else, while
`Settings.domain_pack` reads `DEEPRESEARCH_DOMAIN_PACK` from the environment --
so every value but one killed the process at startup. `NullDomainPack` already
existed as the harness's own composition fixture and was reachable only by
injecting it inside a test, which proves the classes compose but not that an
operator can select a domain.

These tests exercise the path an operator actually uses: the registry, and the
engine reading `settings.domain_pack`. A registry with one entry fails them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.domains.registry import (
    installed_domain_packs,
    load_domain_pack,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

TOPIC = "AI Agent 在财富管理行业的落地机会研究"
#: Sections and vocabulary only the finance pack can produce.
FINANCE_ONLY = ("指标覆盖状态", "主营业务毛利率", "派生指标")


class RegistryInstallsMoreThanOneDomainTests(unittest.TestCase):
    def test_more_than_one_pack_is_installed(self) -> None:
        self.assertGreaterEqual(len(installed_domain_packs()), 2)
        self.assertIn("finance", installed_domain_packs())

    def test_every_installed_name_loads_a_distinct_pack(self) -> None:
        loaded = {name: load_domain_pack(name) for name in installed_domain_packs()}

        self.assertEqual(len(loaded), len(installed_domain_packs()))
        self.assertEqual(
            len({type(pack).__name__ for pack in loaded.values()}),
            len(loaded),
        )

    def test_an_uninstalled_name_is_refused_and_says_what_is_installed(self) -> None:
        with self.assertRaises(ValueError) as caught:
            load_domain_pack("uninstalled")

        message = str(caught.exception)
        self.assertIn("uninstalled", message)
        for name in installed_domain_packs():
            self.assertIn(name, message)


class EveryInstalledPackRunsThroughTheRegistryTests(unittest.TestCase):
    """The acceptance criterion: selection by name, not by injection."""

    def _run(self, name: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    domain_pack=name,
                    structured_logging_enabled=False,
                )
            )
            try:
                state = engine.run(TOPIC, depth_level=1)
            finally:
                engine.close()
        self.assertEqual(state.status, "done")
        return state.final_report or ""

    def test_each_installed_pack_completes_a_workflow(self) -> None:
        for name in installed_domain_packs():
            with self.subTest(pack=name):
                report = self._run(name)
                self.assertIn("## 关键发现", report)

    def test_the_null_pack_contributes_no_finance_behaviour(self) -> None:
        report = self._run("null")

        for marker in FINANCE_ONLY:
            self.assertNotIn(marker, report)

    def test_the_engine_reads_the_name_from_settings(self) -> None:
        """Nothing here injects a pack; the engine resolves it itself."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    domain_pack="null",
                    structured_logging_enabled=False,
                )
            )
            try:
                self.assertEqual(type(engine.domain_pack).__name__, "NullDomainPack")
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main()
