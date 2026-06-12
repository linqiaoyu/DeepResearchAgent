from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import StructuredDataRecord, SymbolInfo
from deepresearch_agent.settings import project_root


class FixtureStructuredDataProvider:
    """Deterministic structured finance data provider backed by recorded fixtures."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self.fixture_path = fixture_path or project_root() / "data" / "mock_data" / "structured_finance.json"
        self._payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        self._symbols = [SymbolInfo.model_validate(item) for item in self._payload.get("symbols", [])]
        self._aliases = {
            alias.lower(): symbol
            for symbol, aliases in self._payload.get("aliases", {}).items()
            for alias in aliases
        }
        self._financial_indicators = [
            StructuredDataRecord.model_validate(item)
            for item in self._payload.get("financial_indicators", [])
        ]
        self._price_history = [
            StructuredDataRecord.model_validate(item)
            for item in self._payload.get("price_history", [])
        ]

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        query = company_name.strip().lower()
        if not query:
            return None
        alias_symbol = self._aliases.get(query)
        for symbol in self._symbols:
            if symbol.symbol == alias_symbol or query in {symbol.name.lower(), symbol.entity.lower(), symbol.symbol}:
                return symbol
        for symbol in self._symbols:
            if query in symbol.name.lower() or query in symbol.entity.lower():
                return symbol
        return None

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        period_set = set(periods or [])
        metric_set = {self._normalize_metric(metric) for metric in (metrics or [])}
        records = [record for record in self._financial_indicators if record.symbol == symbol]
        if period_set:
            records = [record for record in records if record.period in period_set]
        if metric_set:
            records = [record for record in records if self._normalize_metric(record.metric_name) in metric_set]
        return records

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        records = [record for record in self._price_history if record.symbol == symbol]
        return [record for record in records if start_date.isoformat() <= record.period <= end_date.isoformat()]

    def _normalize_metric(self, value: str) -> str:
        aliases = {
            "营业总收入": "营业收入",
            "营收": "营业收入",
        }
        normalized = value.strip()
        return aliases.get(normalized, normalized)
