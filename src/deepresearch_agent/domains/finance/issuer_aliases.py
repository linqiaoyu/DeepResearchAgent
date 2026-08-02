"""Mechanically join SEC registrants to a public CC0 Wikidata snapshot."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache

from deepresearch_agent.settings import project_root


_STOP = frozenset(
    {
        "inc",
        "incorporated",
        "limited",
        "ltd",
        "group",
        "holding",
        "holdings",
        "co",
        "company",
        "corporation",
        "com",
        "technology",
        "auto",
        "up",
    }
)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token for token in re.findall(r"[a-z0-9]+", value.casefold()) if token not in _STOP
    )


@lru_cache(maxsize=1)
def _assets() -> tuple[dict[str, list[str]], list[dict[str, object]]]:
    root = project_root()
    catalog_path = root / "data/finance_sec_issuer_catalog_v1.json"
    snapshot_path = root / "data/finance_wikidata_issuers_v1.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"finance issuer alias asset is missing: {exc.filename}") from exc
    return catalog["issuers"], snapshot["issuers"]


def _idf(snapshot: list[dict[str, object]]) -> dict[str, float]:
    documents = [
        set().union(*(_tokens(name) for name in item["english_names"])) for item in snapshot
    ]
    frequency = Counter(token for tokens in documents for token in tokens)
    return {
        token: math.log((1 + len(documents)) / (1 + count)) + 1
        for token, count in frequency.items()
    }


def _winner(
    english_name: str, snapshot: list[dict[str, object]], weights: dict[str, float]
) -> dict[str, object] | None:
    source = _tokens(english_name)
    scored: list[tuple[float, str, dict[str, object]]] = []
    for item in snapshot:
        overlap = source & set().union(*(_tokens(name) for name in item["english_names"]))
        score = sum(weights.get(token, 0.0) for token in overlap)
        scored.append((score, str(item["wikidata_id"]), item))
    scored.sort(key=lambda row: (-row[0], row[1]))
    if not scored or scored[0][0] <= 0:
        return None
    best = scored[0][0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    # A unique argmax and an IDF-weighted margin reject generic-name collisions.
    if best - runner_up < 0.5:
        return None
    return scored[0][2]


@lru_cache(maxsize=1)
def issuer_aliases() -> dict[str, tuple[str, str]]:
    """Return Chinese public name -> (corpus entity id, SEC registrant name)."""
    catalog, snapshot = _assets()
    weights = _idf(snapshot)
    result: dict[str, tuple[str, str]] = {}
    for entity_id, names in catalog.items():
        for name in names:
            item = _winner(name, snapshot, weights)
            if item is None:
                continue
            for chinese in item["chinese_names"]:
                result[str(chinese)] = (entity_id, name)
    return result


def catalog_entity_for_english(value: str) -> str | None:
    """Corpus-derived English fallback, independent of any public Chinese name."""
    catalog, _snapshot = _assets()
    wanted = _tokens(value)
    for entity_id, names in catalog.items():
        if any(_tokens(name) == wanted for name in names):
            return entity_id
    return None


def public_aliases_for_english(value: str) -> tuple[str, ...]:
    """Public-source aliases for non-corpus issuers; used by the generalization guard."""
    _catalog, snapshot = _assets()
    wanted = _tokens(value)
    for item in snapshot:
        if any(_tokens(name) == wanted for name in item["english_names"]):
            return tuple(str(name) for name in item["chinese_names"])
    return ()
