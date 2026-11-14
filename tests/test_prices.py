"""Fictional securities and prices only; market access is mocked."""

import logging
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_signal.market_calendar import MarketClosed, MarketDataError
from stock_signal.prices import History, JapaneseEquityPrices, YFinanceSource
from stock_signal.valuation import Holding, evaluate

DAY = date(2026, 11, 13)
PREVIOUS = date(2026, 11, 12)
NOW = datetime(2026, 11, 13, 7, 30, tzinfo=timezone.utc)
CODE = "999A"  # An arbitrary fixture, unrelated to any user's actual portfolio.


@pytest.fixture
def history():
    frame = pd.DataFrame(
        {"Close": [100.0, 110.0], "Volume": [1000, 1200], "Stock Splits": [0.0, 0.0]},
        index=pd.DatetimeIndex(["2026-11-12", "2026-11-13"], tz="Asia/Tokyo"),
    )
    return History(
        frame,
        {
            "symbol": f"{CODE}.T",
            "currency": "JPY",
            "exchangeTimezoneName": "Asia/Tokyo",
            "exchangeName": "JPX",
            "instrumentType": "EQUITY",
            "regularMarketTime": datetime(
                2026, 11, 13, 6, 30, tzinfo=timezone.utc
            ).timestamp(),
        },
    )


def fetch(history):
    source = Mock()
    source.load.return_value = history
    quote = JapaneseEquityPrices(source).get_quote(
        CODE, session=DAY, snapshot_date=PREVIOUS, now=NOW
    )
    return quote, source


def test_daily_closes_feed_the_existing_valuation(history):
    quote, source = fetch(history)
    assert quote.close == Decimal("110")
    assert quote.previous_close == Decimal("100")
    assert (quote.session, quote.previous_session) == (DAY, PREVIOUS)
    source.load.assert_called_once_with(
        f"{CODE}.T", start=PREVIOUS, end=date(2026, 11, 14)
    )
    result = evaluate(
        [Holding(CODE, "fictional-account", Decimal("2"), Decimal("80"))],
        {CODE: quote},
        session=DAY,
        previous_session=PREVIOUS,
    ).total
    assert result.market_value == 220
    assert result.daily_change == 20
    assert result.unrealized_gain == 60


@pytest.mark.parametrize(
    "code", ["", "FAKE", "../x", "999a", "999A.T", "0000", "１２３４", None]
)
def test_invalid_or_unsupported_identifiers_never_reach_the_source(code):
    source = Mock()
    with pytest.raises(MarketDataError, match="security code"):
        JapaneseEquityPrices(source).get_quote(
            code, session=DAY, snapshot_date=PREVIOUS, now=NOW
        )
    source.load.assert_not_called()


def test_holiday_or_intraday_request_never_fetches_prices():
    source = Mock()
    provider = JapaneseEquityPrices(source)
    with pytest.raises(MarketClosed):
        provider.get_quote(
            CODE, session=date(2026, 11, 14), snapshot_date=PREVIOUS, now=NOW
        )
    with pytest.raises(MarketDataError, match="not ready"):
        provider.get_quote(
            CODE,
            session=DAY,
            snapshot_date=PREVIOUS,
            now=datetime(2026, 11, 13, tzinfo=timezone.utc),
        )
    source.load.assert_not_called()


@pytest.mark.parametrize(
    "field,bad",
    [
        ("symbol", "OTHER.T"),
        ("currency", "USD"),
        ("exchangeTimezoneName", "UTC"),
        ("exchangeName", "OTHER"),
        ("instrumentType", "MUTUALFUND"),
        ("currency", None),
    ],
)
def test_wrong_or_missing_asset_metadata_is_rejected(history, field, bad):
    history.metadata[field] = bad
    with pytest.raises(MarketDataError, match="metadata"):
        fetch(history)


@pytest.mark.parametrize(
    "stamp",
    [
        None,
        True,
        "invalid",
        float("nan"),
        NOW.timestamp() + 60,
        datetime(2026, 11, 13, 6, 29, tzinfo=timezone.utc).timestamp(),
    ],
)
def test_missing_stale_future_or_invalid_watermark_fails(history, stamp):
    history.metadata["regularMarketTime"] = stamp
    with pytest.raises(MarketDataError):
        fetch(history)


@pytest.mark.parametrize(
    "stamp",
    [
        pd.Timestamp("2026-11-13 15:30", tz="Asia/Tokyo"),
        datetime(2026, 11, 13, 6, 30, tzinfo=timezone.utc),
    ],
)
def test_formatted_vendor_timestamp_is_accepted(history, stamp):
    history.metadata["regularMarketTime"] = stamp
    assert fetch(history)[0].close == 110


@pytest.mark.parametrize("stamp", [datetime(2026, 11, 13, 15, 30), pd.NaT])
def test_naive_or_missing_formatted_timestamp_is_rejected(history, stamp):
    history.metadata["regularMarketTime"] = stamp
    with pytest.raises(MarketDataError):
        fetch(history)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("Close", float("nan")),
        ("Close", float("inf")),
        ("Close", 0),
        ("Close", -1),
        ("Volume", 0),
        ("Volume", float("nan")),
        ("Stock Splits", 2),
        ("Stock Splits", 0.5),
        ("Stock Splits", float("nan")),
    ],
)
def test_missing_prices_zero_volume_and_corporate_actions_fail(history, field, bad):
    frame = history.frame.copy()
    frame[field] = frame[field].astype(float)
    frame.loc[frame.index[-1], field] = bad
    with pytest.raises(MarketDataError):
        fetch(History(frame, history.metadata))


@pytest.mark.parametrize("column", ["Close", "Volume", "Stock Splits"])
def test_missing_required_columns_fail(history, column):
    with pytest.raises(MarketDataError, match="incomplete"):
        fetch(History(history.frame.drop(columns=[column]), history.metadata))


def test_previous_missing_close_or_volume_fails(history):
    for column in ["Close", "Volume"]:
        frame = history.frame.copy()
        frame.loc[frame.index[0], column] = 0
        with pytest.raises(MarketDataError):
            fetch(History(frame, history.metadata))


def test_empty_duplicate_naive_missing_and_wrong_sessions_fail(history):
    frame = history.frame
    naive = frame.copy()
    naive.index = naive.index.tz_localize(None)
    wrong_date = frame.copy()
    wrong_date.index = wrong_date.index - pd.Timedelta(days=1)
    duplicate_columns = pd.concat([frame, frame[["Close"]]], axis=1)
    bad_frames = [
        frame.iloc[:0],
        pd.concat([frame, frame]),
        naive,
        frame.iloc[:1],
        wrong_date,
        duplicate_columns,
        frame.reset_index(),
    ]
    for bad_frame in bad_frames:
        with pytest.raises(MarketDataError):
            fetch(History(bad_frame, history.metadata))


def test_unsorted_rows_and_utc_index_are_matched_by_tokyo_date(history):
    frame = history.frame.iloc[::-1].copy()
    frame.index = frame.index.tz_convert("UTC")
    assert fetch(History(frame, history.metadata))[0].close == 110


def test_split_before_target_date_still_blocks_an_old_snapshot(history):
    frame = history.frame.copy()
    frame.loc[frame.index[0], "Stock Splits"] = 2
    with pytest.raises(MarketDataError, match="corporate action"):
        fetch(History(frame, history.metadata))


def test_snapshot_lookback_detects_older_splits_without_skipping_missing_days(history):
    older = history.frame.iloc[:1].copy()
    older.index = pd.DatetimeIndex(["2026-11-11"], tz="Asia/Tokyo")
    frame = pd.concat([older, history.frame])
    source = Mock()
    source.load.return_value = History(frame, history.metadata)
    provider = JapaneseEquityPrices(source)
    snapshot = date(2026, 11, 11)
    assert (
        provider.get_quote(CODE, session=DAY, snapshot_date=snapshot, now=NOW).close
        == 110
    )
    source.load.assert_called_with(f"{CODE}.T", start=snapshot, end=date(2026, 11, 14))
    frame.loc[frame.index[0], "Stock Splits"] = 2
    with pytest.raises(MarketDataError, match="corporate action"):
        provider.get_quote(CODE, session=DAY, snapshot_date=snapshot, now=NOW)
    # The source cannot silently omit earlier dates and hide corporate actions.
    source.load.return_value = history
    with pytest.raises(MarketDataError, match="complete requested range"):
        provider.get_quote(CODE, session=DAY, snapshot_date=snapshot, now=NOW)


@pytest.mark.parametrize("snapshot", [None, date(2026, 11, 14), date(2019, 1, 1)])
def test_unknown_future_or_out_of_range_snapshot_fails_before_fetching(snapshot):
    source = Mock()
    with pytest.raises(MarketDataError):
        JapaneseEquityPrices(source).get_quote(
            CODE, session=DAY, snapshot_date=snapshot, now=NOW
        )
    source.load.assert_not_called()


def test_provider_error_hides_identifiers_and_vendor_exception(capsys):
    source = Mock()
    source.load.side_effect = MarketDataError("PRIVATE-MARKER from remote")
    with pytest.raises(MarketDataError) as error:
        JapaneseEquityPrices(source).get_quote(
            CODE, session=DAY, snapshot_date=PREVIOUS, now=NOW
        )
    assert "PRIVATE" not in str(error.value)
    assert error.value.__suppress_context__
    assert capsys.readouterr() == ("", "")


def test_vendor_adapter_requests_unadjusted_daily_prices_and_suppresses_output(
    history, monkeypatch, capsys
):
    def fake_history(**kwargs):
        print("PRIVATE-MARKER")
        print("PRIVATE-MARKER", file=sys.stderr)
        logging.getLogger("yfinance").error("PRIVATE-MARKER")
        return history.frame

    ticker = Mock()
    ticker.history.side_effect = fake_history
    ticker.get_history_metadata.return_value = history.metadata
    factory = Mock(return_value=ticker)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=factory))
    result = YFinanceSource().load(f"{CODE}.T", start=PREVIOUS, end=date(2026, 11, 14))
    factory.assert_called_once_with(f"{CODE}.T")
    ticker.history.assert_called_once_with(
        start="2026-11-12",
        end="2026-11-14",
        interval="1d",
        auto_adjust=False,
        back_adjust=False,
        actions=True,
        repair=False,
        keepna=True,
        rounding=False,
        timeout=10,
    )
    assert result.metadata == history.metadata
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("empty", [True, False])
def test_vendor_adapter_failure_has_no_raw_data_and_restores_logger(
    empty, monkeypatch, capsys
):
    ticker = Mock()
    if empty:
        ticker.history.return_value = pd.DataFrame()
    else:
        ticker.history.side_effect = RuntimeError("PRIVATE-MARKER")
    monkeypatch.setitem(
        sys.modules, "yfinance", SimpleNamespace(Ticker=Mock(return_value=ticker))
    )
    logger = logging.getLogger("yfinance")
    before = logger.disabled
    with pytest.raises(MarketDataError) as error:
        YFinanceSource().load(f"{CODE}.T", start=PREVIOUS, end=DAY)
    assert "PRIVATE" not in str(error.value)
    assert logger.disabled == before
    assert capsys.readouterr() == ("", "")
