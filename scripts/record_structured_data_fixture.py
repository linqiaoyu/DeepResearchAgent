from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import SymbolInfo
from deepresearch_agent.settings import project_root
from deepresearch_agent.tools.akshare_structured_data import AKShareStructuredDataProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="Record AKShare structured finance fixture.")
    parser.add_argument("--company", default="宁德时代")
    parser.add_argument("--symbol", default="300750")
    parser.add_argument("--period", action="append", default=["20241231"])
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root() / "data" / "mock_data" / "structured_finance.json",
    )
    args = parser.parse_args()

    provider = AKShareStructuredDataProvider()
    symbol = provider.symbol_resolve(args.company) or SymbolInfo(
        entity=args.company,
        symbol=args.symbol,
        name=args.company,
        data_source="manual",
        as_of=date.today(),
    )
    records = provider.financial_indicators(symbol.symbol, periods=args.period)
    payload = {
        "version": "manual-recording",
        "provider": "akshare",
        "aliases": {symbol.symbol: [symbol.symbol, symbol.entity, symbol.name]},
        "symbols": [symbol.model_dump(mode="json")],
        "financial_indicators": [record.model_dump(mode="json") for record in records],
        "price_history": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
