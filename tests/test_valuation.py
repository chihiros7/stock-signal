"""Entirely fictional holdings; do not derive fixtures from private CSV files."""

from datetime import date
from decimal import Decimal as D

import pytest

from stock_signal.valuation import Holding, Quote, ValuationError, evaluate

SESSION = date(2026, 11, 9)
PREVIOUS = date(2026, 11, 6)


def value(holdings, quotes):
    return evaluate(holdings, quotes, session=SESSION, previous_session=PREVIOUS)


def test_same_symbol_in_different_accounts_and_weighted_totals():
    result = value(
        [
            Holding("FAKE-A", "taxable", D("2"), D("80")),
            Holding("FAKE-A", "nisa", D("3"), D("120")),
            Holding("FAKE-B", "taxable", D("1"), D("400")),
        ],
        {
            "FAKE-A": Quote(SESSION, PREVIOUS, D("110"), D("100")),
            "FAKE-B": Quote(SESSION, PREVIOUS, D("250"), D("300")),
        },
    )
    assert len(result.rows) == 3
    assert result.rows[0].unrealized_gain == D("60")
    assert result.rows[1].unrealized_gain == D("-30")
    assert result.total.market_value == D("800")
    assert result.total.acquisition_value == D("920")
    assert result.total.previous_value == D("800")
    assert result.total.daily_change == 0
    assert result.total.daily_change_percent == 0
    assert result.total.unrealized_gain == D("-120")
    assert result.total.unrealized_gain_percent == D("-120") / D("920") * 100


def test_decimal_precision_and_daily_change_percentage():
    result = value(
        [Holding("FAKE-A", "nisa", D("3"), D("0.1"))],
        {"FAKE-A": Quote(SESSION, PREVIOUS, D("0.3"), D("0.2"))},
    ).total
    assert result.market_value == D("0.9")
    assert result.daily_change == D("0.3")
    assert result.daily_change_percent == D("50")
    assert result.unrealized_gain_percent == D("200")


def test_zero_acquisition_price_has_no_gain_percentage():
    result = value(
        [Holding("FAKE-A", "nisa", D("1"), D("0"))],
        {"FAKE-A": Quote(SESSION, PREVIOUS, D("10"), D("20"))},
    ).total
    assert result.unrealized_gain == 10
    assert result.unrealized_gain_percent is None
    assert result.daily_change_percent == -50


def test_empty_portfolio_does_not_divide_by_zero():
    result = value([], {}).total
    assert result.market_value == 0
    assert result.daily_change_percent is None
    assert result.unrealized_gain_percent is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "-1", "0"])
def test_invalid_prices_and_quantities_are_rejected(bad):
    with pytest.raises(ValuationError):
        Quote(SESSION, PREVIOUS, D(bad), D("1"))
    with pytest.raises(ValuationError):
        Quote(SESSION, PREVIOUS, D("1"), D(bad))
    with pytest.raises(ValuationError):
        Holding("FAKE-A", "nisa", D(bad), D("1"))


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("-1"), 0.1])
def test_invalid_acquisition_price_is_rejected(bad):
    with pytest.raises(ValuationError):
        Holding("FAKE-A", "nisa", D("1"), bad)


@pytest.mark.parametrize("symbol,account", [("", "nisa"), ("FAKE-A", "")])
def test_missing_identifiers_are_rejected(symbol, account):
    with pytest.raises(ValuationError):
        Holding(symbol, account, D("1"), D("1"))


def test_missing_quote_fails_instead_of_valuing_as_zero():
    with pytest.raises(ValuationError, match="unavailable"):
        value([Holding("FAKE-A", "nisa", D("1"), D("1"))], {})


@pytest.mark.parametrize(
    "session,previous",
    [(date(2026, 11, 6), date(2026, 11, 5)), (SESSION, date(2026, 11, 5))],
)
def test_stale_or_wrong_previous_session_fails(session, previous):
    with pytest.raises(ValuationError, match="requested sessions"):
        value(
            [Holding("FAKE-A", "nisa", D("1"), D("1"))],
            {"FAKE-A": Quote(session, previous, D("1"), D("1"))},
        )


def test_duplicate_symbol_and_account_are_rejected():
    holding = Holding("FAKE-A", "nisa", D("1"), D("1"))
    with pytest.raises(ValuationError, match="duplicated"):
        value(
            [holding, holding],
            {"FAKE-A": Quote(SESSION, PREVIOUS, D("1"), D("1"))},
        )


def test_invalid_session_order_is_rejected():
    with pytest.raises(ValuationError, match="sessions"):
        Quote(SESSION, SESSION, D("1"), D("1"))
    with pytest.raises(ValuationError, match="sessions"):
        evaluate([], {}, session=PREVIOUS, previous_session=SESSION)


def test_failures_and_representations_do_not_include_private_values(capsys):
    holding = Holding("PRIVATE-MARKER", "PRIVATE-ACCOUNT", D("7"), D("13"))
    with pytest.raises(ValuationError) as error:
        value([holding], {})
    quote = Quote(SESSION, PREVIOUS, D("10"), D("20"))
    result = value([holding], {holding.symbol: quote})
    assert "PRIVATE" not in str(error.value)
    for obj in [holding, quote, result, result.total, result.rows[0]]:
        assert "PRIVATE" not in repr(obj)
        assert "Decimal" not in repr(obj)
    assert capsys.readouterr() == ("", "")
