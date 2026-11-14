from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from stock_signal.market_calendar import MarketClosed, MarketDataError, TokyoCalendar

JST = ZoneInfo("Asia/Tokyo")


@pytest.fixture(scope="module")
def calendar():
    return TokyoCalendar()


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 11, 14),
        date(2026, 11, 3),
        date(2026, 12, 31),
        date(2026, 1, 2),
        date(2026, 9, 22),
        date(2026, 5, 6),
    ],
)
def test_weekends_exchange_holidays_and_substitute_holidays_are_skipped(calendar, day):
    with pytest.raises(MarketClosed):
        calendar.completed_sessions(day, now=datetime(2027, 1, 1, tzinfo=JST))


@pytest.mark.parametrize(
    "day,previous",
    [
        (date(2026, 11, 9), date(2026, 11, 6)),
        (date(2026, 1, 5), date(2025, 12, 30)),
        (date(2026, 9, 24), date(2026, 9, 18)),
    ],
)
def test_previous_session_crosses_weekends_and_holidays(calendar, day, previous):
    result = calendar.completed_sessions(day, now=datetime(2027, 1, 1, tzinfo=JST))
    assert result.previous_session == previous
    assert result.closes_at.astimezone(JST).hour == 15
    assert result.closes_at.astimezone(JST).minute == 30


@pytest.mark.parametrize("hour,minute", [(9, 0), (15, 29), (15, 30), (15, 44)])
def test_intraday_and_publication_margin_are_rejected(calendar, hour, minute):
    with pytest.raises(MarketDataError, match="not ready"):
        calendar.completed_sessions(
            date(2026, 11, 13), now=datetime(2026, 11, 13, hour, minute, tzinfo=JST)
        )


def test_utc_clock_and_ready_boundary(calendar):
    result = calendar.completed_sessions(
        date(2026, 11, 13), now=datetime(2026, 11, 13, 6, 45, tzinfo=timezone.utc)
    )
    assert result.session == date(2026, 11, 13)


def test_historical_close_time_before_extension(calendar):
    result = calendar.completed_sessions(
        date(2024, 11, 1), now=datetime(2024, 11, 1, 15, 15, tzinfo=JST)
    )
    assert result.closes_at.astimezone(JST).hour == 15
    assert result.closes_at.astimezone(JST).minute == 0


@pytest.mark.parametrize("day", [date(2020, 12, 30), date(2028, 1, 4)])
def test_outside_reviewed_horizon_fails_instead_of_guessing(calendar, day):
    with pytest.raises(MarketDataError, match="does not cover"):
        calendar.completed_sessions(day, now=datetime(2029, 1, 1, tzinfo=JST))


def test_naive_clock_and_datetime_session_are_rejected(calendar):
    with pytest.raises(MarketDataError, match="timezone-aware"):
        calendar.completed_sessions(date(2026, 11, 13), now=datetime(2026, 11, 13, 16))
    with pytest.raises(MarketDataError, match="timezone-aware"):
        calendar.completed_sessions(
            datetime(2026, 11, 13), now=datetime(2026, 11, 13, 16, tzinfo=JST)
        )
