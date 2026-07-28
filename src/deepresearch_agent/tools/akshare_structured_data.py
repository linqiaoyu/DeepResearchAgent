from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import date
from typing import Any

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import StructuredDataRecord, SymbolInfo


class AKShareStructuredDataError(RuntimeError):
    """Raised when AKShare cannot return a normalized structured payload."""


class AKShareStructuredDataProvider:
    fidelity = "real"
    """AKShare-backed adapter behind a small whitelisted structured data contract."""

    def __init__(
        self,
        akshare_module: Any | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        if akshare_module is None:
            import akshare as akshare_module

        self.akshare = akshare_module
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._sleep = sleep_func

    def close(self) -> None:
        """Compatibility hook; each bounded attempt owns its own worker."""

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        query = company_name.strip()
        if not query:
            return None
        frame = self._call(lambda: self.akshare.stock_info_a_code_name(), "symbol_resolve")
        records = frame.to_dict("records")
        for row in records:
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if query in {code, name} or query in name:
                return SymbolInfo(
                    entity=name,
                    symbol=code,
                    exchange=load_domain_pack("finance").equity_exchange_label(),
                    name=name,
                    data_source="AKShare: stock_info_a_code_name",
                    as_of=date.today(),
                )
        return None

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
                or load_domain_pack("finance").default_structured_metrics()
            )
        }
        period_filter = {
            f"{period}1231" if len(period) == 4 and period.isdigit() else period
            for period in (periods or [])
        }
        records: list[StructuredDataRecord] = []
        seen_records: set[tuple[str, str, float, str]] = set()
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
            unit = "%" if "率" in metric_name else "元"
            for column, value in row.items():
                if not str(column).isdigit():
                    continue
                period = str(column)
                if period_filter and period not in period_filter:
                    continue
                numeric_value = self._float_or_none(value)
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
                value = self._float_or_none(row.get(source_column))
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
                    )
                )
        return records

    def _call(self, func: Callable[[], Any], capability: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            future = None
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                # A timed-out call may keep its worker alive.  Reusing a single
                # worker would queue every retry behind that hung call, making
                # the advertised retries ineffective.
                future = executor.submit(func)
                return future.result(timeout=self.timeout_seconds)
            except FutureTimeoutError:
                if future:
                    future.cancel()
                last_error = TimeoutError(
                    f"timeout after {self.timeout_seconds:.3f}s"
                )
            except Exception as exc:
                last_error = exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            if attempt < self.max_retries:
                self._sleep(2**attempt)
        raise AKShareStructuredDataError(f"AKShare {capability} failed: {last_error}") from last_error

    def _normalize_metric(self, metric_name: str) -> str:
        return load_domain_pack("finance").structured_metric_aliases().get(
            metric_name,
            metric_name,
        )

    def _float_or_none(self, value: Any) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None
