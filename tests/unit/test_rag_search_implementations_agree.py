"""R109: `RAG_ENABLED=true` crashed on its first sub-question.

The first live A/B arm for this flag died with

    TypeError: EmptyRagSearchTool.search() got an unexpected keyword argument
    'filter_query'

`Researcher.rag_search` is typed `object`, so three implementations of one call
drifted apart with nothing comparing them, and the two that kept up were the
two some test happened to construct. The flag being off by default is why this
survived: no run in the suite ever reached the pre-index implementation with
retrieval switched on.

The keyword set below is not maintained by hand -- it is read out of the call
site in `researcher.py`, so adding an argument there without updating an
implementation fails here.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from deepresearch_agent.rag.retrieval import EmptyRagSearchTool
from deepresearch_agent.rag.search import RagSearchService
from deepresearch_agent.trajectory_replay import ReplayRagSearch

IMPLEMENTATIONS = (EmptyRagSearchTool, RagSearchService, ReplayRagSearch)


def _call_site_keywords() -> set[str]:
    """Read the keywords `Researcher` actually passes to `rag_search.search`."""

    source = Path(inspect.getsourcefile(EmptyRagSearchTool)).parent.parent
    tree = ast.parse((source / "agents" / "researcher.py").read_text("utf-8"))
    found: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "search"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "rag_search"
        ):
            found.append({kw.arg for kw in node.keywords if kw.arg})
    if not found:
        raise AssertionError("no rag_search.search call site found in researcher.py")
    return set().union(*found)


class RagSearchImplementationsAgreeTests(unittest.TestCase):
    def test_the_call_site_still_looks_the_way_this_test_reads_it(self) -> None:
        """If this fails, the extraction above is stale, not the contract."""
        self.assertIn("filter_query", _call_site_keywords())
        self.assertIn("query", _call_site_keywords())

    def test_every_implementation_accepts_the_call_that_is_made(self) -> None:
        keywords = _call_site_keywords()
        arguments = dict.fromkeys(keywords, None)

        for implementation in IMPLEMENTATIONS:
            with self.subTest(implementation=implementation.__name__):
                signature = inspect.signature(implementation.search)
                # `self` is bound at call time; bind the keywords only.
                signature.bind_partial(None, **arguments)

    def test_the_pre_index_implementation_returns_rather_than_raises(self) -> None:
        """The exact call the live arm made, against the class it reached."""
        result = EmptyRagSearchTool().search(
            query="比亚迪 2024 年归母净利润",
            as_of="2026-07-01",
            filter_query="比亚迪",
            context=None,
        )

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["trace"]["status"], "empty_index")

    def test_no_implementation_invents_a_candidate_without_an_index(self) -> None:
        result = EmptyRagSearchTool().search(
            query="任意问题",
            as_of="2026-07-01",
            filter_query=None,
        )

        self.assertEqual(result["candidates"], [])


if __name__ == "__main__":
    unittest.main()
