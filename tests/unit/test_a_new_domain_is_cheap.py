"""R111: an extension point nobody can afford to use is not an extension point.

R110 registered a second pack and proved a domain is *selectable*. It did not
make one *writable*: `DomainPack` declares 51 methods, and the only existing
implementations answer all 51. "Extensible" cannot rest on a 51-method
obligation.

`BaseDomainPack` answers every capability with "this domain has no opinion", so
a domain overrides only what it decides. These tests measure that cost the only
way that means anything -- by writing a domain and running a workflow with it.
"""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.domains.base import BaseDomainPack
from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.domains.registry import installed_domain_packs
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

TOPIC = "AI Agent 在财富管理行业的落地机会研究"


class ClimateDomain(BaseDomainPack):
    """A domain with exactly one opinion: what its metric names are.

    Deliberately minimal and deliberately not finance. If the harness needs
    more than this to run, the base defaults are not neutral enough.
    """

    name = "climate"

    METRICS = {"排放量": "排放量", "emissions": "排放量"}

    def canonical_metric(self, value: str | None) -> str:
        return self.METRICS.get((value or "").strip(), (value or "").strip())


class ANewDomainIsCheapTests(unittest.TestCase):
    def test_the_base_answers_every_capability_the_protocol_declares(self) -> None:
        declared = {
            name
            for name, member in inspect.getmembers(DomainPack)
            if callable(member) and not name.startswith("_")
        }
        base = BaseDomainPack()

        missing = sorted(name for name in declared if not hasattr(base, name))
        self.assertEqual(missing, [])

    def test_a_new_domain_overrides_a_handful_not_fifty(self) -> None:
        """The number this round set out to move."""
        overrides = {
            name
            for name, member in vars(ClimateDomain).items()
            if callable(member) and not name.startswith("_")
        }

        self.assertLessEqual(len(overrides), 3, sorted(overrides))
        self.assertGreaterEqual(len(vars(BaseDomainPack)), 40)

    def test_it_keeps_its_own_opinion(self) -> None:
        self.assertEqual(ClimateDomain().canonical_metric("emissions"), "排放量")

    def test_it_inherits_no_other_domain_s_opinion(self) -> None:
        """A domain that forgets to override something gets nothing."""
        pack = ClimateDomain()

        self.assertEqual(pack.default_structured_metrics(), ())
        self.assertEqual(pack.primary_source_terms(financial_intent=True), ())
        self.assertIsNone(pack.parse_period("2024"))

    def test_a_workflow_completes_under_the_new_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                ),
                domain_pack=ClimateDomain(),
            )
            try:
                state = engine.run(TOPIC, depth_level=1)
            finally:
                engine.close()

        self.assertEqual(state.status, "done")
        self.assertIn("## 关键发现", state.final_report or "")
        self.assertNotIn("指标覆盖状态", state.final_report or "")

    def test_the_registry_still_installs_the_packs_it_ships(self) -> None:
        """A base class is not a shipped domain; the registry is the list."""
        self.assertEqual(installed_domain_packs(), ("finance", "null"))


if __name__ == "__main__":
    unittest.main()
