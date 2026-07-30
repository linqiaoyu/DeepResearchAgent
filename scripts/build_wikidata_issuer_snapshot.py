"""Freeze a public CC0 issuer-name snapshot without consulting evaluation data."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import certifi
import httpx


QUERY = '''SELECT DISTINCT ?item ?enLabel ?zhName ?ticker WHERE {
  ?item p:P414 ?listing .
  ?listing ps:P414 ?exchange .
  VALUES ?exchange { wd:Q13677 wd:Q82059 }
  ?item wdt:P17 wd:Q148 .
  ?item rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") .
  ?item (rdfs:label|skos:altLabel) ?zhName
    FILTER(LANG(?zhName) IN ("zh", "zh-hans", "zh-cn")) .
  OPTIONAL { ?item wdt:P249 ?ticker }
}'''
SOURCE_URL = "https://query.wikidata.org/sparql"


def build(raw: Path, output: Path) -> dict[str, object]:
    bindings = json.loads(raw.read_text(encoding="utf-8"))["results"]["bindings"]
    by_id: dict[str, dict[str, object]] = {}
    for binding in bindings:
        item = binding["item"]["value"].rsplit("/", 1)[-1]
        entry = by_id.setdefault(item, {"wikidata_id": item, "english_names": set(), "chinese_names": set(), "tickers": set()})
        entry["english_names"].add(binding["enLabel"]["value"])
        name = binding.get("zhName", binding.get("zhLabel", {})).get("value")
        if name:
            entry["chinese_names"].add(name)
        ticker = binding.get("ticker", {}).get("value")
        if ticker:
            entry["tickers"].add(ticker)
    issuers = [{key: sorted(value) if isinstance(value, set) else value for key, value in entry.items()} for entry in by_id.values()]
    issuers.sort(key=lambda value: str(value["wikidata_id"]))
    result: dict[str, object] = {"schema_version": 2, "source_url": SOURCE_URL, "license": "CC0-1.0", "attribution_required": False, "snapshot_utc": datetime.now(UTC).replace(microsecond=0).isoformat(), "query": QUERY, "issuer_count": len(issuers), "issuers": issuers, "not_an_evaluation_asset": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.raw, args.output)
    print(json.dumps({"issuer_count": result["issuer_count"], "source": "CC0 Wikidata snapshot"}))


if __name__ == "__main__":
    main()
