"""Round-083 offline assertions for SEC concept selection and metric outcomes."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx

from deepresearch_agent.tools import SecCompanyFactsProvider, StructuredDataUnsupportedMetric


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sec_companyfacts_nio_fy2024.json"


def _provider() -> SecCompanyFactsProvider:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files/company_tickers.json":
            return httpx.Response(200, json={"0": {
                "cik_str": 1736541, "ticker": "NIO", "title": "NIO Inc.",
            }})
        if request.url.path.endswith("CIK0001736541.json"):
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return SecCompanyFactsProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0
    )


def _unsupported(provider: SecCompanyFactsProvider, metric: str) -> bool:
    try:
        provider.financial_indicators("CIK0001736541", periods=["20241231"], metrics=[metric])
    except StructuredDataUnsupportedMetric:
        return True
    return False


def main() -> int:
    provider = _provider()
    revenue = provider.financial_indicators("CIK0001736541", periods=["20241231"], metrics=["营业收入"])
    gross = provider.financial_indicators("CIK0001736541", periods=["20241231"], metrics=["毛利"])
    empty = provider.financial_indicators("CIK0001736541", periods=["20151231"], metrics=["营业收入"])
    values = [item.value for item in revenue]
    print(f"revenue_records={len(revenue)}")
    print(f"revenue_value={values[0] if len(values) == 1 else 'missing'}")
    print(f"revenue_unit={revenue[0].unit if len(revenue) == 1 else 'missing'}")
    print(f"gross_records={len(gross)}")
    print(f"gross_value={gross[0].value if len(gross) == 1 else 'missing'}")
    print(f"gross_unit={gross[0].unit if len(gross) == 1 else 'missing'}")
    print(f"gross_margin_unsupported={int(_unsupported(provider, '毛利率'))}")
    print(f"pe_ratio_unsupported={int(_unsupported(provider, '市盈率'))}")
    print(f"empty_result_not_unsupported={int(empty == [])}")
    return int(not (
        len(revenue) == 1 and values == [Decimal("65731559000")] and revenue[0].unit == "CNY"
        and len(gross) == 1 and gross[0].value == Decimal("6492762000") and gross[0].unit == "CNY"
        and _unsupported(provider, "毛利率") and _unsupported(provider, "市盈率") and empty == []
    ))


if __name__ == "__main__":
    raise SystemExit(main())
