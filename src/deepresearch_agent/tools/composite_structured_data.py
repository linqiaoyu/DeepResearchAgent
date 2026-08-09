"""Route a structured-data request to a provider that can serve the issuer.

R101: provider selection was a single environment string read before the
question was known, and live mode set it to the A-share provider. A question
about a US-listed issuer was therefore sent to a China A-share source, whose
``symbol_resolve`` timed out twice, and the delivered report said
``未取得可引用的原始披露事实`` while the provider holding the answer was never
called. Selecting one data source at launch means the agent can only ever
answer about the market the operator picked.

Each provider already declares its own surface. This composite asks them in
order and keeps the first answer, so a provider that cannot serve an issuer
costs a miss rather than the whole question.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from deepresearch_agent.observability import JsonLogger
from deepresearch_agent.tools.provider import (
    StructuredDataProvider,
    StructuredDataRecord,
    SymbolInfo,
)


@dataclass(frozen=True)
class RoutingEvent:
    """One provider's answer to one request, including the ones that missed."""

    provider: str
    capability: str
    #: ``served`` | ``no_match`` | ``empty`` | ``error``
    outcome: str
    detail: str = ""


@dataclass
class _NamedProvider:
    name: str
    provider: StructuredDataProvider


@dataclass
class CompositeStructuredDataProvider:
    """Try each provider in order; the first with an answer serves the request.

    Order matters for what a miss costs, not for correctness. The SEC provider
    resolves against a table it fetches once, so a miss is cheap and immediate;
    the AKShare provider resolves over the network under a 15-second timeout, so
    trying it first makes every non-A-share question pay that timeout before
    reaching a provider that can answer. Cheap-miss providers therefore come
    first.
    """

    providers: Sequence[_NamedProvider]
    logger: JsonLogger | None = None
    routing_events: list[RoutingEvent] = field(default_factory=list)
    _served_by: dict[str, str] = field(default_factory=dict)

    @property
    def fidelity(self) -> str:
        """Declare the provenance of the route, never of one member alone.

        R109: `auto` is what `--live` selects, and `auto` builds this class,
        which declared no fidelity at all. The first live golden run therefore
        recorded `structured_data: unknown` -- the field whose entire job is to
        prove a run used real sources could not classify the provider the live
        arm selects by default. A route is only as real as its least real
        member, and a route whose members disagree is `mixed`, which
        `AGENTS.md` §7 forbids calling a real run.
        """

        declared = {
            getattr(item.provider, "fidelity", "unknown")
            for item in self.providers
        }
        if not declared:
            return "unknown"
        if len(declared) == 1:
            return declared.pop()
        return "mixed"

    def supports_request(self, capability: str) -> bool:
        return any(
            self._supports(item.provider, capability) for item in self.providers
        )

    def close(self) -> None:
        for item in self.providers:
            closer = getattr(item.provider, "close", None)
            if callable(closer):
                closer()

    def set_run_context(self, context: Any) -> None:
        """Bind counted egress on every provider that counts it."""

        for item in self.providers:
            binder = getattr(item.provider, "set_run_context", None)
            if callable(binder):
                binder(context)

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        for item in self._eligible("symbol_resolve"):
            resolved = self._attempt(
                item,
                "symbol_resolve",
                lambda provider: provider.symbol_resolve(company_name),
            )
            if resolved is not None:
                # Remember who resolved it so the follow-up request for the same
                # symbol does not start over at a provider that cannot serve it.
                self._served_by[resolved.symbol] = item.name
                return resolved
        return None

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        return self._first_non_empty(
            symbol,
            "financial_indicators",
            lambda provider: provider.financial_indicators(
                symbol, periods=periods, metrics=metrics
            ),
        )

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        return self._first_non_empty(
            symbol,
            "price_history",
            lambda provider: provider.price_history(symbol, start_date, end_date),
        )

    def _first_non_empty(
        self,
        symbol: str,
        capability: str,
        call: Any,
    ) -> list[StructuredDataRecord]:
        for item in self._ordered_for(symbol, capability):
            records = self._attempt(item, capability, call)
            if records:
                return list(records)
        return []

    def _attempt(self, item: _NamedProvider, capability: str, call: Any) -> Any:
        try:
            result = call(item.provider)
        except Exception as exc:  # provider-specific; a miss must not end the run
            self._record(item.name, capability, "error", f"{type(exc).__name__}: {exc}")
            return None
        if result:
            self._record(item.name, capability, "served")
            return result
        self._record(
            item.name,
            capability,
            "no_match" if capability == "symbol_resolve" else "empty",
        )
        return None

    def _eligible(self, capability: str) -> list[_NamedProvider]:
        return [
            item
            for item in self.providers
            if self._supports(item.provider, capability)
        ]

    def _ordered_for(self, symbol: str, capability: str) -> list[_NamedProvider]:
        eligible = self._eligible(capability)
        owner = self._served_by.get(symbol)
        if owner is None:
            return eligible
        return sorted(eligible, key=lambda item: item.name != owner)

    @staticmethod
    def _supports(provider: StructuredDataProvider, capability: str) -> bool:
        declared = getattr(provider, "supports_request", None)
        if callable(declared):
            return bool(declared(capability))
        # A provider that declares nothing is offered every request, which is
        # how the single-provider configurations behaved before this existed.
        return True

    def _record(
        self, provider: str, capability: str, outcome: str, detail: str = ""
    ) -> None:
        self.routing_events.append(
            RoutingEvent(
                provider=provider,
                capability=capability,
                outcome=outcome,
                detail=detail,
            )
        )
        if self.logger:
            self.logger.event(
                "structured_data_routing",
                provider=provider,
                capability=capability,
                outcome=outcome,
                detail=detail,
            )


def build_composite(
    named_providers: Sequence[tuple[str, StructuredDataProvider]],
    *,
    logger: JsonLogger | None = None,
) -> CompositeStructuredDataProvider:
    return CompositeStructuredDataProvider(
        providers=[_NamedProvider(name=name, provider=provider) for name, provider in named_providers],
        logger=logger,
    )
