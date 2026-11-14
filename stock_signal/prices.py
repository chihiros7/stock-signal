"""Replaceable market-data source and strict daily-close validation.

The Yahoo adapter is for development verification. Production use for multiple
Discord users requires a separate review of data-use and redistribution terms.
"""

import io
import logging
import re
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

import pandas as pd

from stock_signal.market_calendar import MarketDataError, TokyoCalendar
from stock_signal.valuation import Quote


@dataclass(frozen=True, repr=False)
class History:
    frame: pd.DataFrame
    metadata: Mapping


class HistorySource(Protocol):
    def load(self, symbol: str, *, start: date, end: date) -> History: ...


class QuoteProvider(Protocol):
    def get_quote(
        self, code: str, *, session: date, snapshot_date: date, now: datetime
    ) -> Quote: ...


@contextmanager
def _quiet_vendor():
    """Serial adapter calls only: suppress vendor identifiers and raw errors.

    yfinance uses its own logger and may also write to stdout/stderr. Never
    enable vendor debug output in jobs processing private portfolio information.
    """
    logger = logging.getLogger("yfinance")
    was_disabled = logger.disabled
    logger.disabled = True
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield
    finally:
        logger.disabled = was_disabled


class YFinanceSource:
    def load(self, symbol: str, *, start: date, end: date) -> History:
        # A deferred import keeps the optional live adapter off the default CLI.
        with _quiet_vendor():
            try:
                import yfinance

                ticker = yfinance.Ticker(symbol)
                frame = ticker.history(
                    start=start.isoformat(),
                    end=end.isoformat(),  # yfinance's end is exclusive
                    interval="1d",
                    auto_adjust=False,
                    back_adjust=False,
                    actions=True,
                    repair=False,
                    keepna=True,
                    rounding=False,
                    timeout=10,
                )
                if frame.empty:
                    raise MarketDataError("Market history is unavailable.")
                metadata = ticker.get_history_metadata()
                # Copy plain keys only, without invoking lazy metadata lookups.
                keys = (
                    "symbol",
                    "currency",
                    "exchangeTimezoneName",
                    "exchangeName",
                    "instrumentType",
                    "regularMarketTime",
                )
                return History(frame, {key: metadata.get(key) for key in keys})
            except Exception:
                raise MarketDataError(
                    "Market history could not be retrieved."
                ) from None


def _decimal(value, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception:
        raise MarketDataError("A market-data number is invalid.") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise MarketDataError("A market-data number is invalid.")
    return result


class JapaneseEquityPrices:
    """Fail closed for missing/stale prices and unsupported market data.

    No fallback to an older date, estimated zero price, adjusted close, or a
    partial portfolio. The source receives only ticker and date range, never
    quantities, accounts, acquisition prices or the CSV itself.
    """

    def __init__(
        self,
        source: HistorySource,
        calendar: TokyoCalendar | None = None,
    ) -> None:
        self._source = source
        self._calendar = calendar if calendar is not None else TokyoCalendar()

    def get_quote(
        self, code: str, *, session: date, snapshot_date: date, now: datetime
    ) -> Quote:
        if not isinstance(code, str) or not re.fullmatch(r"[1-9][0-9A-Z]{3}", code):
            raise MarketDataError("A supported Japanese security code is required.")
        sessions = self._calendar.completed_sessions(session, now=now)
        if type(snapshot_date) is not date or snapshot_date > session:
            raise MarketDataError("A verified holdings snapshot date is required.")
        start = min(sessions.previous_session, snapshot_date)
        expected_dates = self._calendar.sessions_between(start, session)
        symbol = f"{code}.T"
        try:
            history = self._source.load(
                symbol,
                start=start,
                end=sessions.session + timedelta(days=1),
            )
        except Exception:
            raise MarketDataError("Market history could not be retrieved.") from None
        try:
            return self._validate(
                history, symbol, sessions, snapshot_date, expected_dates, now
            )
        except MarketDataError:
            raise
        except Exception:
            raise MarketDataError("Market data could not be validated.") from None

    @staticmethod
    def _validate(
        history, symbol, sessions, snapshot_date, expected_dates, now
    ) -> Quote:
        metadata = history.metadata
        if (
            metadata.get("symbol") != symbol
            or metadata.get("currency") != "JPY"
            or metadata.get("exchangeTimezoneName") != "Asia/Tokyo"
            or metadata.get("exchangeName") not in {"JPX", "TYO"}
            or metadata.get("instrumentType") not in {"EQUITY", "ETF"}
        ):
            raise MarketDataError("Market metadata does not match the requested asset.")
        # A day-labelled bar may still be an intraday/stale price. Check the
        # vendor's last-trade watermark as well as the local market-close clock.
        stamp = metadata.get("regularMarketTime")
        if isinstance(stamp, datetime):
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise MarketDataError("The market-data timestamp is unavailable.")
            last_trade = stamp.astimezone(timezone.utc)
        elif isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            last_trade = datetime.fromtimestamp(stamp, timezone.utc)
        else:
            raise MarketDataError("The market-data timestamp is unavailable.")
        if last_trade < sessions.closes_at or last_trade > now:
            raise MarketDataError("The market-data timestamp is not current enough.")

        frame = history.frame
        if (
            frame.empty
            or not {"Close", "Volume", "Stock Splits"}.issubset(frame.columns)
            or not frame.columns.is_unique
            or not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is None
        ):
            raise MarketDataError("Daily market history is incomplete.")
        dates = frame.index.tz_convert("Asia/Tokyo").date
        if len(set(dates)) != len(dates):
            raise MarketDataError("Daily market history has duplicate dates.")
        if set(dates) != set(expected_dates):
            raise MarketDataError(
                "Daily history for the complete requested range is required."
            )
        current = frame.iloc[list(dates).index(sessions.session)]
        previous = frame.iloc[list(dates).index(sessions.previous_session)]
        for day, split in zip(dates, frame["Stock Splits"], strict=True):
            if day >= snapshot_date and _decimal(split) != 0:
                # An old CSV doesn't become valid when a split is no longer
                # today's event. Keep blocking until a verified refresh.
                raise MarketDataError(
                    "A corporate action requires manual verification."
                )
        _decimal(current["Volume"], positive=True)
        _decimal(previous["Volume"], positive=True)
        return Quote(
            sessions.session,
            sessions.previous_session,
            _decimal(current["Close"], positive=True),
            _decimal(previous["Close"], positive=True),
        )
