"""Tokyo cash-equity sessions; all clock inputs must include a timezone."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import exchange_calendars


class MarketDataError(ValueError):
    """Public-safe error; never include identifiers, prices or vendor messages."""


class MarketClosed(MarketDataError):
    """The requested date is not a trading day; daily jobs should skip it."""


@dataclass(frozen=True)
class TradingSessions:
    session: date
    previous_session: date
    closes_at: datetime


class TokyoCalendar:
    """Pinned calendar horizon; extend after reviewing the next JPX calendar.

    The horizon covers the checked deployment period. Do not extrapolate dates
    outside it, or assume a Japanese national holiday calendar is sufficient.
    """

    def __init__(self) -> None:
        self._calendar = exchange_calendars.get_calendar(
            "XTKS", start="2020-01-01", end="2027-12-31"
        )

    def completed_sessions(self, session: date, *, now: datetime) -> TradingSessions:
        if type(session) is not date or now.tzinfo is None or now.utcoffset() is None:
            raise MarketDataError("A date and a timezone-aware clock are required.")
        # The first year initializes history for previous-session lookup.
        if not date(2021, 1, 1) <= session <= date(2027, 12, 31):
            raise MarketDataError("The market calendar does not cover this date.")
        if not self._calendar.is_session(session):
            raise MarketClosed("The requested date is not a trading day.")
        closes_at = self._calendar.session_close(session).to_pydatetime()
        # Leave a publication margin as well as refusing an intraday valuation.
        if now < closes_at + timedelta(minutes=15):
            raise MarketDataError("The closing-price publication window is not ready.")
        previous = self._calendar.previous_session(session).date()
        return TradingSessions(session, previous, closes_at)

    def sessions_between(self, start: date, end: date) -> tuple[date, ...]:
        if (
            type(start) is not date
            or type(end) is not date
            or not date(2021, 1, 1) <= start <= end <= date(2027, 12, 31)
        ):
            raise MarketDataError("The market calendar does not cover this range.")
        return tuple(day.date() for day in self._calendar.sessions_in_range(start, end))
