"""R109: the field that proves a run is real could not read the live default.

`--live` selects `DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=auto`, `auto` builds
`CompositeStructuredDataProvider`, and that class declared no `fidelity`. The
first live golden round therefore recorded
`provider_fidelity={'search': 'real', 'structured_data': 'unknown', ...}` while
AKShare was serving real records for both requested metrics -- see
`artifacts/109/live1/work/Q01/state.json`. `AGENTS.md` §7 forbids calling a run
real unless every layer is real, so a layer that cannot classify itself makes
the whole claim unavailable.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.provenance.manifest import _realness
from deepresearch_agent.tools.composite_structured_data import (
    CompositeStructuredDataProvider,
    build_composite,
)
from deepresearch_agent.tools.structured_data_factory import (
    build_structured_data_provider,
)
from deepresearch_agent.workflow.engine import _provider_fidelity


class _Provider:
    def __init__(self, fidelity: str | None) -> None:
        if fidelity is not None:
            self.fidelity = fidelity

    def supports_request(self, capability: str) -> bool:
        return True


class RoutedProviderFidelityTests(unittest.TestCase):
    def test_a_route_of_real_providers_is_real(self) -> None:
        composite = build_composite(
            [("sec", _Provider("real")), ("akshare", _Provider("real"))]
        )

        self.assertEqual(composite.fidelity, "real")

    def test_a_route_holding_a_fixture_is_mixed(self) -> None:
        composite = build_composite(
            [("sec", _Provider("real")), ("fixture", _Provider("fixture"))]
        )

        self.assertEqual(composite.fidelity, "mixed")

    def test_a_member_that_declares_nothing_is_not_assumed_real(self) -> None:
        composite = build_composite(
            [("sec", _Provider("real")), ("mystery", _Provider(None))]
        )

        self.assertEqual(composite.fidelity, "mixed")

    def test_an_empty_route_is_unknown(self) -> None:
        self.assertEqual(
            CompositeStructuredDataProvider(providers=[]).fidelity, "unknown"
        )

    def test_the_engine_no_longer_flattens_the_declaration(self) -> None:
        self.assertEqual(_provider_fidelity(_Provider("mixed")), "mixed")
        self.assertEqual(_provider_fidelity(_Provider("real")), "real")
        self.assertEqual(_provider_fidelity(_Provider("nonsense")), "unknown")

    def test_a_mixed_layer_downgrades_the_run_without_erasing_it(self) -> None:
        """`unknown` said nothing; `mixed` says the run is not a real run."""
        run = {
            "search": "real",
            "structured_data": "mixed",
            "disclosure": "real",
            "llm": "real",
        }

        self.assertEqual(_realness(run), "mixed")
        self.assertNotEqual(_realness(run), "real")

    def test_the_live_default_classifies_itself(self) -> None:
        """The defect, pinned at the name the live arm actually passes."""
        provider = build_structured_data_provider(
            {"DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "auto"}
        )

        self.assertNotEqual(_provider_fidelity(provider), "unknown")
        self.assertEqual(_provider_fidelity(provider), "real")


if __name__ == "__main__":
    unittest.main()
