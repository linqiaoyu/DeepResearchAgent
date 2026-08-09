"""R111: the authoritative data layer failed on a 10-second timing margin.

R109 measured the symptom: 46 structured requests, 16 records, 30 symbol
resolution failures, and 0 records for 长江电力 and 比亚迪 across 8 of 8 live
runs each. The cause was neither a missing mapping nor a dead endpoint.
`stock_info_a_code_name()` returns all 5,539 listings and resolves all three
golden-set issuers correctly -- in 25.2 seconds, because it walks 17 paginated
sub-requests. The provider's bounded call allows 15.

Measured after this change: a cold resolve costs 6.5s and a warm one 0.001s,
and six issuers resolve, including the two that had never resolved once.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.tools.symbol_table import (
    SymbolTable,
    build_symbol_table,
    load_symbol_table,
)


class _Frame:
    """The `.to_dict('records')` shape the provider frames expose."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def to_dict(self, _orient: str) -> list[dict[str, str]]:
        return list(self._rows)


SH_ROWS = [
    {"证券代码": "600519", "证券简称": "贵州茅台"},
    {"证券代码": "600900", "证券简称": "长江电力"},
]
SZ_ROWS = [
    {"A股代码": "002594", "A股简称": "比亚迪"},
    {"A股代码": "000333", "A股简称": "美的集团"},
]


#: Read through the pack, not by importing a concrete domain: the same rule
#: the core obeys applies to its tests.
EQUITY_LISTING_SOURCES = load_domain_pack("finance").equity_listing_sources()
#: Correct, complete, and 10 seconds over the provider's call budget.
SLOW_COMBINED_LISTING_ENDPOINT = "stock_info_a_code_name"


def _fetch(endpoint: str) -> _Frame:
    if endpoint == "stock_info_sh_name_code":
        return _Frame(SH_ROWS)
    if endpoint == "stock_info_sz_name_code":
        return _Frame(SZ_ROWS)
    raise AssertionError(f"unexpected endpoint {endpoint}")


class TheSlowEndpointIsNotUsedTests(unittest.TestCase):
    def test_the_25_second_endpoint_is_not_in_the_source_list(self) -> None:
        """It answers correctly and cannot finish inside the call budget."""
        self.assertNotIn(
            SLOW_COMBINED_LISTING_ENDPOINT,
            [endpoint for endpoint, _code, _name in EQUITY_LISTING_SOURCES],
        )

    def test_both_exchanges_are_consulted(self) -> None:
        self.assertEqual(len(EQUITY_LISTING_SOURCES), 2)


class BuildingTheTableTests(unittest.TestCase):
    def test_it_composes_every_exchange(self) -> None:
        table = build_symbol_table(_fetch, EQUITY_LISTING_SOURCES)

        self.assertEqual(table.resolve("贵州茅台"), ("600519", "贵州茅台"))
        self.assertEqual(table.resolve("比亚迪"), ("002594", "比亚迪"))
        self.assertEqual(len(table.sources), 2)

    def test_one_unreachable_exchange_does_not_deny_the_other(self) -> None:
        def half_broken(endpoint: str) -> _Frame:
            if endpoint == "stock_info_sh_name_code":
                raise ConnectionError("reset by peer")
            return _fetch(endpoint)

        table = build_symbol_table(half_broken, EQUITY_LISTING_SOURCES)

        self.assertEqual(table.resolve("比亚迪"), ("002594", "比亚迪"))
        self.assertIsNone(table.resolve("贵州茅台"))
        self.assertEqual(table.sources, ("stock_info_sz_name_code",))

    def test_no_reachable_exchange_raises_rather_than_returning_empty(self) -> None:
        def broken(_endpoint: str) -> _Frame:
            raise ConnectionError("reset by peer")

        with self.assertRaises(LookupError):
            build_symbol_table(broken, EQUITY_LISTING_SOURCES)


class ResolutionRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = build_symbol_table(_fetch, EQUITY_LISTING_SOURCES)

    def test_an_exact_code_resolves(self) -> None:
        self.assertEqual(self.table.resolve("600900"), ("600900", "长江电力"))

    def test_an_exact_name_resolves(self) -> None:
        self.assertEqual(self.table.resolve("长江电力"), ("600900", "长江电力"))

    def test_a_partial_name_resolves_to_nothing(self) -> None:
        """Attaching another issuer's financials to a prefix is the harm."""
        self.assertIsNone(self.table.resolve("长江"))
        self.assertIsNone(self.table.resolve("贵州茅台股份"))

    def test_an_unknown_name_resolves_to_nothing(self) -> None:
        self.assertIsNone(self.table.resolve("不存在的公司"))

    def test_blank_input_resolves_to_nothing(self) -> None:
        self.assertIsNone(self.table.resolve("   "))


class CachingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.cache = Path(self._dir.name) / "symbols.json"
        self.addCleanup(self._dir.cleanup)

    def test_the_first_load_fetches_and_writes_the_cache(self) -> None:
        calls: list[str] = []

        def counting(endpoint: str) -> _Frame:
            calls.append(endpoint)
            return _fetch(endpoint)

        load_symbol_table(counting, EQUITY_LISTING_SOURCES, cache_path=self.cache)

        self.assertEqual(len(calls), 2)
        self.assertTrue(self.cache.is_file())

    def test_a_fresh_cache_costs_no_network_call(self) -> None:
        load_symbol_table(_fetch, EQUITY_LISTING_SOURCES, cache_path=self.cache)

        def refuse(_endpoint: str) -> _Frame:
            raise AssertionError("a fresh cache must not refetch")

        table = load_symbol_table(refuse, EQUITY_LISTING_SOURCES, cache_path=self.cache)

        self.assertEqual(table.resolve("比亚迪"), ("002594", "比亚迪"))

    def test_a_stale_cache_is_refetched(self) -> None:
        load_symbol_table(_fetch, EQUITY_LISTING_SOURCES, cache_path=self.cache)
        later = datetime.now(UTC) + timedelta(days=30)
        calls: list[str] = []

        def counting(endpoint: str) -> _Frame:
            calls.append(endpoint)
            return _fetch(endpoint)

        load_symbol_table(counting, EQUITY_LISTING_SOURCES, cache_path=self.cache, now=later)

        self.assertEqual(len(calls), 2)

    def test_a_corrupt_cache_is_replaced_rather_than_crashing(self) -> None:
        self.cache.write_text("{not json", encoding="utf-8")

        table = load_symbol_table(_fetch, EQUITY_LISTING_SOURCES, cache_path=self.cache)

        self.assertEqual(table.resolve("贵州茅台"), ("600519", "贵州茅台"))

    def test_the_cache_records_where_it_came_from(self) -> None:
        load_symbol_table(_fetch, EQUITY_LISTING_SOURCES, cache_path=self.cache)
        payload = json.loads(self.cache.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["sources"]), 2)
        self.assertTrue(datetime.fromisoformat(payload["fetched_at"]))

    def test_a_round_trip_preserves_the_table(self) -> None:
        table = build_symbol_table(_fetch, EQUITY_LISTING_SOURCES)

        restored = SymbolTable.from_json(table.to_json())

        self.assertEqual(restored.resolve("美的集团"), ("000333", "美的集团"))
        self.assertEqual(restored.sources, table.sources)


class TheProviderUsesTheCacheTests(unittest.TestCase):
    def test_resolution_costs_one_fetch_for_many_issuers(self) -> None:
        """The R109 shape: one run resolves several issuers' sub-questions."""
        from deepresearch_agent.domains.registry import load_domain_pack
        from deepresearch_agent.tools.akshare_structured_data import (
            AKShareStructuredDataProvider,
        )

        calls: list[str] = []

        class _Module:
            def stock_info_sh_name_code(self) -> _Frame:
                calls.append("sh")
                return _Frame(SH_ROWS)

            def stock_info_sz_name_code(self) -> _Frame:
                calls.append("sz")
                return _Frame(SZ_ROWS)

        with tempfile.TemporaryDirectory() as tmp:
            provider = AKShareStructuredDataProvider(
                akshare_module=_Module(),
                isolate_processes=False,
                domain_pack=load_domain_pack("finance"),
                symbol_cache_path=Path(tmp) / "symbols.json",
            )
            resolved = [
                provider.symbol_resolve(name)
                for name in ("贵州茅台", "长江电力", "比亚迪")
            ]

        self.assertEqual([item.symbol for item in resolved], ["600519", "600900", "002594"])
        self.assertEqual(len(calls), 2, "one table fetch, not one per issuer")


if __name__ == "__main__":
    unittest.main()
