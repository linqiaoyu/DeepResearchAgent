"""R105: a reported amount must reach the reader as the figure the source printed."""

from __future__ import annotations

import unittest
from decimal import Decimal

from deepresearch_agent.tools.akshare_structured_data import (
    AKShareStructuredDataProvider,
)


class StructuredValuePrecisionTests(unittest.TestCase):
    """Moutai's 2024 revenue reached the reader as `174,144,069,958.24997 元`.

    The provider converted every reported amount to a binary float, and
    `Decimal(float)` keeps that float's exact binary expansion. A financial
    report stating revenue to five wrong decimal places of a yuan is not a
    rounding blemish -- it is the first thing a reader would disbelieve.
    """

    def _value(self, raw: object, unit: str = "元") -> Decimal | None:
        # Constructed without touching AKShare: the conversion is pure.
        provider = AKShareStructuredDataProvider.__new__(AKShareStructuredDataProvider)
        return provider._decimal_or_none(raw, unit=unit)

    def test_a_reported_amount_keeps_the_decimal_the_source_printed(self) -> None:
        self.assertEqual(self._value("174144069958.25"), Decimal("174144069958.25"))

    def test_the_figure_moutai_reached_the_reader_with_is_quantised(self) -> None:
        """The literal value from R105's live run, and the filed figure it should be."""

        value = self._value(Decimal("174144069958.24997"))

        assert value is not None
        self.assertEqual(value, Decimal("174144069958.25"))
        self.assertNotIn("24997", str(value))

    def test_no_currency_amount_carries_more_than_a_fen(self) -> None:
        for raw in ("174144069958.24997", "150560330316.44998", 1.005, "0.001"):
            value = self._value(raw)
            assert value is not None
            self.assertLessEqual(
                -value.as_tuple().exponent, 2, f"{raw!r} kept sub-fen precision"
            )

    def test_a_non_currency_unit_keeps_its_precision(self) -> None:
        """A ratio or a count is not money and must not be rounded to a fen."""

        value = self._value("0.91234", unit="%")

        self.assertEqual(value, Decimal("0.91234"))

    def test_thousands_separators_survive(self) -> None:
        self.assertEqual(self._value("150,560,330,316.45"), Decimal("150560330316.45"))

    def test_a_non_numeric_cell_is_not_a_value(self) -> None:
        for raw in (None, "", "--", "N/A", True, False):
            self.assertIsNone(self._value(raw), f"{raw!r} became a number")

    def test_an_infinite_value_is_refused(self) -> None:
        self.assertIsNone(self._value(float("inf")))
        self.assertIsNone(self._value(float("nan")))


if __name__ == "__main__":
    unittest.main()
