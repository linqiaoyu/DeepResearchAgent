"""A cached issuer name-to-symbol table for the exchange-listing provider.

R111 measured why issuer resolution failed for most names. It was not a missing
mapping and not a dead endpoint: the provider's combined listing endpoint
returns all 5,539 listings and resolves correctly -- in **25.2 seconds**,
because it walks 17 paginated sub-requests. The provider's bounded call gives it
**15 seconds**. So the call timed out every time, `symbol_resolve` returned
nothing, and the authoritative structured layer produced 0 records for 2 of the
3 issuers in the R109 golden set, across 16 of 16 live runs.

Two things follow. The table is fetched from the per-exchange endpoints, which
answer in 3.3s and 3.8s and together cover the same listings; and it is cached,
so the cost is paid once per TTL rather than once per sub-question.

The cache is a runtime artifact, not a managed fixture: it is derived from a
live source, carries the endpoints and timestamp it came from, and is rebuilt
when stale. Nothing here invents a mapping -- an unresolvable name stays
unresolved.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

#: A listing source is `(endpoint, code_column, name_column)`. Which endpoints
#: exist and what their columns are called is provider and market knowledge,
#: so the domain supplies them and this module stays free of both.
ListingSource = tuple[str, str, str]
DEFAULT_CACHE_PATH = Path("data/runtime/a_share_symbols.json")
DEFAULT_TTL = timedelta(days=7)


@dataclass(frozen=True)
class SymbolTable:
    """Issuer name to listing code, with the provenance of the fetch."""

    codes_by_name: Mapping[str, str]
    sources: tuple[str, ...]
    fetched_at: datetime

    def resolve(self, query: str) -> tuple[str, str] | None:
        """Return `(code, name)` for an exact code or an exact name.

        A code is unique; a name is not guaranteed to be, so an ambiguous name
        resolves to nothing rather than to whichever issuer sorted first. That
        rule is inherited from the provider this replaces and is the reason it
        is safe to attach financial data to the result.
        """

        text = query.strip()
        if not text:
            return None
        by_code = {code: name for name, code in self.codes_by_name.items()}
        if text in by_code:
            return text, by_code[text]
        matches = [
            (code, name)
            for name, code in self.codes_by_name.items()
            if name == text
        ]
        return matches[0] if len(matches) == 1 else None

    def to_json(self) -> str:
        return json.dumps(
            {
                "sources": list(self.sources),
                "fetched_at": self.fetched_at.isoformat(),
                "codes_by_name": dict(self.codes_by_name),
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, payload: str) -> SymbolTable:
        data = json.loads(payload)
        return cls(
            codes_by_name=dict(data["codes_by_name"]),
            sources=tuple(data.get("sources", ())),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
        )

    def is_stale(self, ttl: timedelta, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) - self.fetched_at > ttl


def build_symbol_table(
    fetch: Callable[[str], Any],
    sources: Sequence[ListingSource],
    *,
    now: datetime | None = None,
) -> SymbolTable:
    """Compose the table from every exchange endpoint that answers.

    `fetch` takes an endpoint name and returns its frame, so the caller decides
    how the call is bounded and isolated. An endpoint that fails is skipped:
    one exchange being unreachable must not deny the issuers listed on the
    other.
    """

    codes: dict[str, str] = {}
    used: list[str] = []
    for endpoint, code_column, name_column in sources:
        try:
            frame = fetch(endpoint)
        except Exception:
            continue
        if frame is None:
            continue
        rows = frame.to_dict("records")
        added = False
        for row in rows:
            name = str(row.get(name_column, "")).strip()
            code = str(row.get(code_column, "")).strip()
            if name and code and name not in codes:
                codes[name] = code
                added = True
        if added:
            used.append(endpoint)
    if not codes:
        raise LookupError("no exchange listing endpoint returned a usable table")
    return SymbolTable(
        codes_by_name=codes,
        sources=tuple(used),
        fetched_at=now or datetime.now(UTC),
    )


def load_symbol_table(
    fetch: Callable[[str], Any],
    sources: Sequence[ListingSource],
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    ttl: timedelta = DEFAULT_TTL,
    now: datetime | None = None,
) -> SymbolTable:
    """Return a fresh-enough table, fetching only when the cache cannot serve."""

    if cache_path.is_file():
        try:
            cached = SymbolTable.from_json(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError, ValueError):
            cached = None
        if cached is not None and not cached.is_stale(ttl, now):
            return cached
    table = build_symbol_table(fetch, sources, now=now)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(table.to_json(), encoding="utf-8")
    return table
