"""Where this market publishes its listing table, and under which columns.

R111: the provider's combined listing endpoint answers correctly and takes 25.2
seconds against a 15-second call budget, so it timed out on every request and
issuer resolution never succeeded. The per-venue endpoints below answer in 3.3s
and 3.8s and cover the same listings between them.

This is market knowledge -- venue names, column names -- so it lives with the
domain rather than in the shared cache that consumes it.
"""

from __future__ import annotations

#: `(endpoint, code_column, name_column)`, one per listing venue.
EQUITY_LISTING_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("stock_info_sh_name_code", "证券代码", "证券简称"),
    ("stock_info_sz_name_code", "A股代码", "A股简称"),
)
#: Deliberately unused: correct, complete, and 10 seconds over the budget.
SLOW_COMBINED_LISTING_ENDPOINT = "stock_info_a_code_name"
