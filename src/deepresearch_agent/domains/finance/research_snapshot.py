from __future__ import annotations

from typing import Any


def demo_numeric_claim(claims: list[Any]) -> Any | None:
    return next((claim for claim in claims if "营业收入" in claim.key.metric), None)


def demo_scope_claim(claims: list[Any], numeric_change: Any | None) -> Any | None:
    return next(
        (
            claim
            for claim in claims
            if claim is not numeric_change and "扣非净利润" in claim.key.metric
        ),
        None,
    )


def scope_change_summary(label: str) -> str:
    return f"{label}发生口径调整，相关数值不作直接同比。"
