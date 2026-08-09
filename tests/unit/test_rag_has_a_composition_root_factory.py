"""R110: retrieval was the one capability with no factory, so it was inert.

`build_search_provider` and `build_structured_data_provider` sit at the
composition root; the disclosure source is composed there too. `RagSearchService`
was constructed **zero times** in `src/` -- its only construction site was
`scripts/run_research_package.py` -- and `capability_setup` read:

    rag_search=(rag_search or EmptyRagSearchTool()) if settings.rag_enabled else None

So `RAG_ENABLED=true` through `DeepResearchEngine` could not retrieve anything.
The R109 live A/B arm recorded `provider_fidelity.rag_search='fixture'` and the
`rag_search/not_found/empty_result` degradation on all three cases: a capability
that is on and inert, the defect `validate_capability_invariants` exists for.

The pre-index implementation is still reachable. It is no longer what you get by
forgetting to configure a backend.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.config_validation import ConfigurationError
from deepresearch_agent.rag.factory import (
    UnsupportedRagBackendError,
    build_rag_search,
    missing_rag_configuration,
)
from deepresearch_agent.rag.retrieval import EmptyRagSearchTool
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "deepresearch_agent"
LIVE_ENVIRONMENT = {
    "DASHSCOPE_API_KEY": "k",
    "DEEPRESEARCH_QDRANT_URL": "http://localhost:6333",
    "DEEPRESEARCH_QDRANT_COLLECTION": "c",
    "DEEPRESEARCH_RAG_INDEX_VERSION": "v1",
}


def _settings(tmp: Path, **overrides: object) -> Settings:
    return Settings(storage_path=tmp / "research.db", **overrides)


class TheFactoryIsTheOnlyConstructionPathTests(unittest.TestCase):
    def test_the_service_is_constructed_in_exactly_one_module(self) -> None:
        """A second construction site is a second composition root."""
        sites = sorted(
            path.relative_to(SOURCE_ROOT).as_posix()
            for path in SOURCE_ROOT.rglob("*.py")
            if "RagSearchService(" in path.read_text(encoding="utf-8")
        )

        self.assertEqual(sites, ["rag/factory.py"])

    def test_capability_setup_no_longer_substitutes_an_empty_index(self) -> None:
        source = (SOURCE_ROOT / "workflow" / "capability_setup.py").read_text("utf-8")

        self.assertIn("build_rag_search(", source)
        # The substitution expression itself, not a mention of the class.
        self.assertNotIn("rag_search or EmptyRagSearchTool()", source)


class UnconfiguredRetrievalIsRefusedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_disabled_retrieval_needs_nothing(self) -> None:
        self.assertEqual(missing_rag_configuration(_settings(self.tmp), {}), [])

    def test_enabled_retrieval_names_every_missing_variable(self) -> None:
        missing = missing_rag_configuration(
            _settings(self.tmp, rag_enabled=True), {}
        )

        self.assertEqual(
            missing,
            [
                "DASHSCOPE_API_KEY",
                "DEEPRESEARCH_QDRANT_URL",
                "DEEPRESEARCH_QDRANT_COLLECTION",
                "DEEPRESEARCH_RAG_INDEX_VERSION",
            ],
        )

    def test_building_an_unconfigured_backend_raises_rather_than_degrades(self) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            build_rag_search(_settings(self.tmp, rag_enabled=True), environ={})

        self.assertIn("DEEPRESEARCH_QDRANT_URL", caught.exception.missing)

    def test_an_unknown_backend_name_is_refused(self) -> None:
        with self.assertRaises(UnsupportedRagBackendError):
            missing_rag_configuration(
                _settings(self.tmp, rag_enabled=True),
                {"DEEPRESEARCH_RAG_BACKEND": "elasticsearch"},
            )

    def test_the_engine_fails_closed_instead_of_retrieving_nothing(self) -> None:
        """The R109 defect, at the layer an operator meets it."""
        with self.assertRaises(ConfigurationError):
            DeepResearchEngine(
                _settings(
                    self.tmp,
                    rag_enabled=True,
                    injection_guard_enabled=True,
                    structured_logging_enabled=False,
                )
            ).close()


class ThePreIndexPathStaysReachableTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_it_is_selected_by_name(self) -> None:
        built = build_rag_search(
            _settings(self.tmp, rag_enabled=True),
            environ={"DEEPRESEARCH_RAG_BACKEND": "empty"},
        )

        self.assertIsInstance(built, EmptyRagSearchTool)

    def test_naming_it_needs_no_other_configuration(self) -> None:
        self.assertEqual(
            missing_rag_configuration(
                _settings(self.tmp, rag_enabled=True),
                {"DEEPRESEARCH_RAG_BACKEND": "empty"},
            ),
            [],
        )

    def test_a_configured_live_backend_is_not_the_empty_one(self) -> None:
        """Configuration complete: the factory must reach the real service."""
        environment = dict(LIVE_ENVIRONMENT)
        environment["DEEPRESEARCH_RAG_DATABASE"] = str(self.tmp / "missing.db")

        # The database is the last precondition; reaching it proves the factory
        # selected the live path rather than silently returning an empty index.
        with self.assertRaises(FileNotFoundError):
            build_rag_search(
                _settings(self.tmp, rag_enabled=True), environ=environment
            )


if __name__ == "__main__":
    unittest.main()
