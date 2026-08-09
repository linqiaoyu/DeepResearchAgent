from __future__ import annotations

import multiprocessing
import queue
import re
import time
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from deepresearch_agent.domains.protocols import StructuredDataDomain
from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.schemas import StructuredDataRecord, SymbolInfo


class AKShareStructuredDataError(RuntimeError):
    """Raised when AKShare cannot return a normalized structured payload."""


def _call_in_child(func: Callable[[], Any], result_queue: Any) -> None:
    """Run an untrusted provider call outside the harness process."""
    try:
        result_queue.put((True, func()))
    except BaseException as exc:
        result_queue.put((False, (type(exc).__name__, str(exc))))


class AKShareStructuredDataProvider:
    fidelity = "real"
    """AKShare-backed adapter behind a small whitelisted structured data contract."""

    def __init__(
        self,
        akshare_module: Any | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        sleep_func: Callable[[float], None] = time.sleep,
        isolate_processes: bool = True,
        domain_pack: StructuredDataDomain | None = None,
    ) -> None:
        if akshare_module is None:
            import akshare as akshare_module

        self.akshare = akshare_module
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._sleep = sleep_func
        self._isolate_processes = isolate_processes
        self._domain_pack = resolve_domain_capability(
            domain_pack, consumer="AKShareStructuredDataProvider"
        )

    def close(self) -> None:
        """Compatibility hook; each bounded attempt owns its own process."""

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        query = company_name.strip()
        if not query:
            return None
        frame = self._call(lambda: self.akshare.stock_info_a_code_name(), "symbol_resolve")
        records = frame.to_dict("records")
        normalized = [
            (str(row.get("code", "")).strip(), str(row.get("name", "")).strip())
            for row in records
        ]
        # A stock code is globally unique in this provider.  A name is not, so
        # accepting a partial name (or the first duplicate) would silently
        # attach another issuer's financial data to the request.
        exact_codes = [(code, name) for code, name in normalized if code == query]
        exact_names = [(code, name) for code, name in normalized if name == query]
        matches = exact_codes or exact_names
        if len(matches) != 1:
            return None
        code, name = matches[0]
        return SymbolInfo(
            entity=name,
            symbol=code,
            exchange=self._domain_pack.equity_exchange_label(),
            name=name,
            data_source="AKShare: stock_info_a_code_name",
            as_of=date.today(),
        )

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        frame = self._call(
            lambda: self.akshare.stock_financial_abstract(symbol=symbol),
            "financial_indicators",
        )
        # Callers that already hold a six-digit exchange symbol must not pay
        # for a second, full-market symbol-table request merely to decorate
        # the record's entity name.
        symbol_info = None if re.fullmatch(r"\d{6}", symbol) else self.symbol_resolve(symbol)
        entity = symbol_info.entity if symbol_info else symbol
        metric_filter = {
            self._normalize_metric(metric)
            for metric in (
                metrics
                or self._domain_pack.default_structured_metrics()
            )
        }
        period_filter = {
            f"{period}1231" if len(period) == 4 and period.isdigit() else period
            for period in (periods or [])
        }
        records: list[StructuredDataRecord] = []
        seen_records: set[tuple[str, str, Decimal, str]] = set()
        raw_rows = frame.to_dict("records")
        raw_metrics = {str(row.get("指标", "")).strip() for row in raw_rows}
        for row in raw_rows:
            raw_metric_name = str(row.get("指标", "")).strip()
            metric_name = self._normalize_metric(raw_metric_name)
            # Prefer the canonical provider row when a registered alias and
            # its canonical spelling are both present in the same frame.
            if raw_metric_name != metric_name and metric_name in raw_metrics:
                continue
            if metric_name not in metric_filter:
                continue
            unit = self._domain_pack.structured_metric_unit(metric_name) or "unknown"
            for column, value in row.items():
                if not str(column).isdigit():
                    continue
                period = str(column)
                if period_filter and period not in period_filter:
                    continue
                numeric_value = self._decimal_or_none(value, unit=unit)
                if numeric_value is None:
                    continue
                record_key = (metric_name, period, numeric_value, unit)
                if record_key in seen_records:
                    continue
                seen_records.add(record_key)
                records.append(
                    StructuredDataRecord(
                        entity=entity,
                        symbol=symbol,
                        metric_name=metric_name,
                        period=period,
                        dimension="累计",
                        value=numeric_value,
                        unit=unit,
                        data_source="AKShare: stock_financial_abstract",
                        as_of=date.today(),
                        source_pub_date=None,
                    )
                )
        return records

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        frame = self._call(
            lambda: self.akshare.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="",
            ),
            "price_history",
        )
        symbol_info = self.symbol_resolve(symbol)
        entity = symbol_info.entity if symbol_info else symbol
        records: list[StructuredDataRecord] = []
        for row in frame.to_dict("records"):
            day = str(row.get("日期", "")).strip()[:10]
            if not day:
                continue
            for source_column, metric_name in (("收盘", "收盘价"), ("最高", "最高价"), ("最低", "最低价")):
                value = self._decimal_or_none(row.get(source_column), unit="元/股")
                if value is None:
                    continue
                records.append(
                    StructuredDataRecord(
                        entity=entity,
                        symbol=symbol,
                        metric_name=metric_name,
                        period=day,
                        dimension="日频未复权",
                        value=value,
                        unit="元/股",
                        data_source="AKShare: stock_zh_a_hist",
                        as_of=date.today(),
                        source_pub_date=None,
                    )
                )
        return records

    def _call(self, func: Callable[[], Any], capability: str) -> Any:
        if not self._isolate_processes:
            return func()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            context = multiprocessing.get_context("fork")
            result_queue = context.Queue(maxsize=1)
            process = context.Process(target=_call_in_child, args=(func, result_queue))
            try:
                process.start()
                # R098: read the result before waiting for the child to exit.
                # A queue is a pipe with a bounded buffer, so a child returning
                # more than the buffer holds blocks inside `put` until the
                # parent reads -- while the parent was blocked in `join`
                # waiting for that same child to exit. The two waited on each
                # other until the timeout, on every attempt, for every result
                # too large to fit the pipe. `stock_financial_abstract` for
                # 600519 returns an 80x104 frame, so the A-share structured
                # path deadlocked deterministically and had never once
                # succeeded in a live run.
                try:
                    ok, payload = result_queue.get(timeout=self.timeout_seconds)
                except queue.Empty:
                    # Thread cancellation cannot stop a blocking provider
                    # call.  Each attempt therefore owns a process that can be
                    # terminated before the retry budget is consumed.
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=1)
                        last_error = TimeoutError(
                            f"timeout after {self.timeout_seconds:.3f}s"
                        )
                    else:
                        last_error = AKShareStructuredDataError(
                            f"worker exited with code {process.exitcode} without a result"
                        )
                else:
                    # The child is done writing; it exits on its own now.
                    process.join(timeout=self.timeout_seconds)
                    if ok:
                        return payload
                    error_type, error_message = payload
                    last_error = AKShareStructuredDataError(
                        f"{error_type}: {error_message}"
                    )
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1)
                result_queue.close()
                result_queue.join_thread()
            if attempt < self.max_retries:
                self._sleep(2**attempt)
        raise AKShareStructuredDataError(f"AKShare {capability} failed: {last_error}") from last_error

    def _normalize_metric(self, metric_name: str) -> str:
        return self._domain_pack.structured_metric_aliases().get(
            metric_name,
            metric_name,
        )

    #: The smallest unit any of these currencies is reported in. A figure with
    #: more decimals than this is arithmetic residue, not disclosure.
    _CURRENCY_UNITS = frozenset({"元", "元/股", "CNY", "cny", "RMB", "rmb"})
    _CURRENCY_QUANTUM = Decimal("0.01")

    def _decimal_or_none(self, value: Any, *, unit: str | None = None) -> Decimal | None:
        """Carry a reported amount as a decimal, without inventing precision.

        R105: this returned a binary float and the record field is a `Decimal`,
        so the float's binary expansion became the value. Moutai's 2024 revenue
        reached the reader as `174,144,069,958.24997 元` -- revenue stated to
        five decimal places of a yuan, four of them wrong. That is the first
        thing a reader would disbelieve, whatever else the report gets right.

        Two separate faults, so two fixes. Money does not pass through a binary
        float. And an amount in a currency is quantised to that currency's
        smallest unit, because no filing reports a fraction of a fen and
        carrying one forward only launders the provider's arithmetic residue
        into a figure that looks precise.
        """

        if value is None or isinstance(value, bool):
            return None
        try:
            # `str` first: a pandas float64 renders as its shortest round-trip
            # decimal, which is the closest thing to the figure the source holds.
            numeric = Decimal(str(value).strip().replace(",", ""))
        except (TypeError, ValueError, InvalidOperation):
            return None
        if not numeric.is_finite():
            return None
        if unit in self._CURRENCY_UNITS and -numeric.as_tuple().exponent > 2:
            return numeric.quantize(self._CURRENCY_QUANTUM, rounding=ROUND_HALF_UP)
        return numeric
