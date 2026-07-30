from __future__ import annotations

import unittest

from deepresearch_agent.domains.finance import issuer_aliases as aliases


class IssuerAliasGeneralizationTests(unittest.TestCase):
    def test_no_chinese_label_issuers_keep_corpus_derived_english_path(self) -> None:
        # Mutating any catalog registrant below makes this guard fail.
        for name, expected in {"Qifu Technology, Inc.": "qfin", "FinVolution Group": "finv", "LexinFintech Holdings Ltd.": "lx", "Full Truck Alliance Co. Ltd.": "ymm"}.items():
            self.assertEqual(aliases.catalog_entity_for_english(name), expected)

    def test_removing_public_alias_does_not_remove_corpus_identity(self) -> None:
        # Deleting Alibaba's public entry must not change the filing-derived fallback.
        catalog, snapshot = aliases._assets()
        reduced = [item for item in snapshot if "Alibaba Group" not in item["english_names"]]
        self.assertLess(len(reduced), len(snapshot))
        self.assertEqual(aliases.catalog_entity_for_english(catalog["baba"][0]), "baba")

    def test_public_snapshot_generalizes_beyond_corpus(self) -> None:
        # Removing either public item makes the corresponding assertion fail.
        self.assertIn("中通快递", aliases.public_aliases_for_english("ZTO Express"))
        self.assertIn("贝壳找房", aliases.public_aliases_for_english("Beike"))

    def test_snapshot_has_non_eval_entities_and_join_has_no_ambiguous_pairs(self) -> None:
        catalog, snapshot = aliases._assets()
        corpus_names = {name for names in catalog.values() for name in names}
        non_eval = [item for item in snapshot if not set(item["english_names"]) & corpus_names]
        self.assertGreaterEqual(len(non_eval), 50)
        mapping = aliases.issuer_aliases()
        self.assertTrue(mapping)
        self.assertEqual(len(mapping), len(set(mapping)))
