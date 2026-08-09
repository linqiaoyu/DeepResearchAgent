"""R101: a structured-data request must reach a provider that can serve it."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

from deepresearch_agent.tools.composite_structured_data import build_composite
from deepresearch_agent.tools.provider import StructuredDataRecord, SymbolInfo
from deepresearch_agent.tools.structured_data_factory import build_structured_data_provider


class _Provider:
    """A provider that serves one market and misses everything else."""

    def __init__(
        self,
        name: str,
        *,
        serves: set[str],
        capabilities: set[str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.name = name
        self.serves = serves
        self.capabilities = capabilities
        self.raises = raises
        self.resolve_calls: list[str] = []
        self.indicator_calls: list[str] = []

    def supports_request(self, capability: str) -> bool:
        if self.capabilities is None:
            return True
        return capability in self.capabilities

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        self.resolve_calls.append(company_name)
        if self.raises is not None:
            raise self.raises
        if company_name in self.serves:
            return SymbolInfo(
                entity=company_name,
                symbol=company_name,
                exchange="test",
                name=company_name,
                data_source=self.name,
                as_of=date(2026, 1, 1),
            )
        return None

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        self.indicator_calls.append(symbol)
        if self.raises is not None:
            raise self.raises
        if symbol not in self.serves:
            return []
        return [
            StructuredDataRecord(
                entity=symbol,
                symbol=symbol,
                metric_name=(metrics or ["营业收入"])[0],
                period=(periods or ["20241231"])[0],
                dimension="合计",
                value=Decimal("1"),
                unit="元",
                data_source=self.name,
                as_of=date(2026, 1, 1),
            )
        ]

    def price_history(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[StructuredDataRecord]:
        return []


class CompositeRoutingTests(unittest.TestCase):
    """The failure this exists to prevent is one live run's whole answer."""

    def _pair(self, **kwargs: object) -> tuple[_Provider, _Provider]:
        us = _Provider("sec", serves={"NIO"}, **kwargs)  # type: ignore[arg-type]
        cn = _Provider("akshare", serves={"600519"})
        return us, cn

    def test_a_us_issuer_is_not_answered_only_by_the_a_share_provider(self) -> None:
        """R100's last live run in one assertion.

        `_configure_mode("live")` selected AKShare, the planner asked for a
        US-listed issuer, `symbol_resolve` timed out twice, and the reader was
        told no citable disclosure existed while the SEC provider -- which
        returns this filer's revenue for both requested years -- was never
        called.
        """

        us, cn = self._pair()
        composite = build_composite([("sec", us), ("akshare", cn)])

        symbol = composite.symbol_resolve("NIO")
        assert symbol is not None
        records = composite.financial_indicators(symbol.symbol, periods=["20241231"])

        self.assertEqual(symbol.data_source, "sec")
        self.assertEqual([record.data_source for record in records], ["sec"])

    def test_an_a_share_issuer_still_reaches_the_a_share_provider(self) -> None:
        us, cn = self._pair()
        composite = build_composite([("sec", us), ("akshare", cn)])

        symbol = composite.symbol_resolve("600519")
        assert symbol is not None
        records = composite.financial_indicators(symbol.symbol, periods=["20241231"])

        self.assertEqual(symbol.data_source, "akshare")
        self.assertEqual([record.data_source for record in records], ["akshare"])

    def test_a_failing_provider_does_not_take_the_question_down_with_it(self) -> None:
        """AKShare raised `timeout after 15.000s` twice and the run answered nothing."""

        broken = _Provider("akshare", serves={"600519"}, raises=TimeoutError("timeout after 15.000s"))
        working = _Provider("sec", serves={"NIO"})
        composite = build_composite([("akshare", broken), ("sec", working)])

        symbol = composite.symbol_resolve("NIO")

        assert symbol is not None
        self.assertEqual(symbol.data_source, "sec")
        self.assertIn(
            "error",
            [event.outcome for event in composite.routing_events],
            "a provider failure was not recorded",
        )

    def test_a_provider_is_not_offered_a_capability_it_does_not_declare(self) -> None:
        narrow = _Provider("sec", serves={"NIO"}, capabilities={"financial_indicators"})
        wide = _Provider("akshare", serves={"NIO"})
        composite = build_composite([("sec", narrow), ("akshare", wide)])

        composite.symbol_resolve("NIO")

        self.assertEqual(narrow.resolve_calls, [])
        self.assertEqual(wide.resolve_calls, ["NIO"])

    def test_the_follow_up_request_goes_to_whoever_resolved_the_symbol(self) -> None:
        """Otherwise every indicator request restarts at a provider that missed."""

        us, cn = self._pair()
        composite = build_composite([("akshare", cn), ("sec", us)])

        symbol = composite.symbol_resolve("NIO")
        assert symbol is not None
        cn.indicator_calls.clear()
        composite.financial_indicators(symbol.symbol, periods=["20241231"])

        self.assertEqual(cn.indicator_calls, [])

    def test_live_mode_no_longer_pins_the_run_to_one_market(self) -> None:
        """`auto` is what `_configure_mode("live")` sets; it must route, not pin."""

        with mock.patch(
            "deepresearch_agent.tools.structured_data_factory.AKShareStructuredDataProvider",
            side_effect=ModuleNotFoundError(name="akshare"),
        ):
            provider = build_structured_data_provider(
                {"DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "auto"}
            )

        self.assertEqual(
            [item.name for item in provider.providers],
            ["sec"],
        )

    def test_an_explicit_single_provider_is_still_exactly_that(self) -> None:
        provider = build_structured_data_provider(
            {"DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "sec"}
        )

        self.assertFalse(hasattr(provider, "providers"))


if __name__ == "__main__":
    unittest.main()
