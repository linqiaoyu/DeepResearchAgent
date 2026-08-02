"""Verify that distinct SEC facts retain distinct, stable Evidence IDs."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from deepresearch_agent.agents import ResearcherAgent
from deepresearch_agent.tools import SecCompanyFactsProvider


FIXTURE = Path(__file__).parents[1] / "tests/fixtures/sec_companyfacts_nio_fy2024.json"


def _provider() -> SecCompanyFactsProvider:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files/company_tickers.json":
            return httpx.Response(200, json={"0": {"cik_str": 1736541, "ticker": "NIO", "title": "NIO Inc."}})
        if request.url.path.endswith("CIK0001736541.json"):
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return SecCompanyFactsProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)


def main() -> int:
    records = _provider().financial_indicators("CIK0001736541", periods=["20241231"], metrics=["营业收入", "毛利"])
    researcher = ResearcherAgent(structured_data_provider=_provider())
    first = [researcher._evidence_from_record("084", "q", record) for record in records]
    second = [researcher._evidence_from_record("084", "q", record) for record in records]
    ids = {item.id for item in first}
    by_metric = {item.structured_record.metric_name: item for item in first if item.structured_record}
    collision_count = len(first) - len(ids)
    stable = int([item.id for item in first] == [item.id for item in second])
    print(f"records={len(records)}")
    print(f"evidence_ids={len(ids)}")
    print(f"collision_count={collision_count}")
    print(f"revenue_value={by_metric['营业收入'].structured_record.value}")
    print(f"gross_value={by_metric['毛利'].structured_record.value}")
    print(f"id_stable_across_runs={stable}")
    return int(not (len(records) == len(ids) == 2 and collision_count == 0 and stable == 1))


if __name__ == "__main__":
    raise SystemExit(main())
