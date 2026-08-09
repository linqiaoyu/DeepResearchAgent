"""R110: prose could state a capability default the code contradicts.

`sync_agents_settings.py` rewrites every `FLAG=true|false` token in AGENTS.md,
.env.example and README.md, so those are safe. Nothing read the sentences. R110
found six live contradictions that had passed every gate:

    README.md:144                PROGRESSIVE_DELIVERY_ENABLED is true, text says off
    README.md:144                TRAJECTORY_RECORD_ENABLED is true, text says off
    docs/decision_weaving.md:62  DECISION_WEAVING_ENABLED is true, text says off
    docs/decision_weaving.md:62  NUMERIC_CHECK_ENABLED is true, text says off
    docs/numeric_consistency.md:3   NUMERIC_CHECK_ENABLED is true, text says off
    docs/numeric_consistency.md:31  NUMERIC_CHECK_ENABLED is true, text says off

The hard part is not detecting a claim, it is not binding one to the wrong
capability. A token-proximity rule was prototyped first and measured at 2 of 3
precision on the real documents -- it read `rag_search` is conditionally
registered only when `RAG_ENABLED=true`. Its current default is ... as a stale
default claim. A gate that blocks correct documentation is worse than none, so
binding stops at a clause boundary and that rule is what these tests pin.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_doc_flag_claims import (
    PROSE_ALIASES,
    DocFlagClaimError,
    contradictions,
    tracked_markdown,
    validate_alias_table,
)

from deepresearch_agent.settings import boolean_setting_defaults


class DocFlagClaimBindingTests(unittest.TestCase):
    DEFAULTS = {"A_ENABLED": True, "B_ENABLED": False}

    def _found(self, line: str, tmp: Path) -> list[str]:
        path = tmp / "doc.md"
        path.write_text(line, encoding="utf-8")
        return contradictions([path], self.DEFAULTS)

    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_a_stale_off_claim_is_caught(self) -> None:
        self.assertEqual(len(self._found("`A_ENABLED` 默认关闭。", self.tmp)), 1)

    def test_a_stale_on_claim_is_caught(self) -> None:
        self.assertEqual(len(self._found("`B_ENABLED` 默认开启。", self.tmp)), 1)

    def test_an_enumeration_binds_to_every_capability_it_names(self) -> None:
        found = self._found("`A_ENABLED` 与 `B_ENABLED` 默认关闭。", self.tmp)

        self.assertEqual(len(found), 1)
        self.assertIn("A_ENABLED", found[0])

    def test_a_correct_claim_is_not_reported(self) -> None:
        self.assertEqual(self._found("`A_ENABLED` 默认开启。", self.tmp), [])
        self.assertEqual(self._found("`B_ENABLED` 默认关闭。", self.tmp), [])

    def test_a_claim_does_not_reach_across_a_clause_boundary(self) -> None:
        """The false positive the clause rule exists to prevent."""
        line = "`A_ENABLED=true`；此外其余尚未验证的能力全部保持关闭。"

        self.assertEqual(self._found(line, self.tmp), [])

    def test_a_conditional_is_not_a_default_claim(self) -> None:
        """`only when X=true. Its current default is ...` must stay legal."""
        line = "`rag` is registered only when `B_ENABLED=true`：默认开启的是空实现。"

        self.assertEqual(self._found(line, self.tmp), [])

    def test_an_alias_binds_when_prose_omits_the_flag_name(self) -> None:
        aliases = dict(PROSE_ALIASES)
        try:
            PROSE_ALIASES.clear()
            PROSE_ALIASES["A_ENABLED"] = ("alpha packer",)
            self.assertEqual(len(self._found("alpha packer 默认关闭。", self.tmp)), 1)
        finally:
            PROSE_ALIASES.clear()
            PROSE_ALIASES.update(aliases)

    def test_an_alias_naming_no_real_flag_is_refused(self) -> None:
        aliases = dict(PROSE_ALIASES)
        try:
            PROSE_ALIASES["NOT_A_FLAG"] = ("nonsense",)
            with self.assertRaises(DocFlagClaimError):
                validate_alias_table(boolean_setting_defaults())
        finally:
            PROSE_ALIASES.clear()
            PROSE_ALIASES.update(aliases)


class TrackedDocumentationTests(unittest.TestCase):
    def test_every_alias_names_a_real_flag(self) -> None:
        validate_alias_table(boolean_setting_defaults())

    def test_the_repository_documentation_agrees_with_settings(self) -> None:
        found = contradictions(tracked_markdown(), boolean_setting_defaults())

        self.assertEqual(found, [], "\n".join(found))

    def test_round_records_are_not_rewritten_by_this_rule(self) -> None:
        """`docs/decisions/<round>/` states what was true then, not now."""
        self.assertEqual(
            [p for p in tracked_markdown() if str(p).startswith("docs/decisions/")],
            [],
        )


if __name__ == "__main__":
    unittest.main()
