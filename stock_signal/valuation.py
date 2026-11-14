"""JPY-only portfolio calculations; no network access, logging or persistence."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class ValuationError(ValueError):
    """A safe error whose message does not contain portfolio data."""


def _number(value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValuationError("A finite decimal is required.")
    if value < 0 or (positive and value == 0):
        raise ValuationError("A value is outside the supported range.")


@dataclass(frozen=True, repr=False)
class Holding:
    symbol: str
    account: str
    quantity: Decimal
    acquisition_price: Decimal

    def __post_init__(self) -> None:
        if not self.symbol or not self.account:
            raise ValuationError("A holding identifier is missing.")
        _number(self.quantity, positive=True)
        _number(self.acquisition_price)


@dataclass(frozen=True, repr=False)
class Quote:
    """Unadjusted JPY closes; session dates must come from a market calendar.

    A provider must validate currency, market close, and corporate actions before
    constructing this object. Splits must not be silently treated as daily losses.
    """

    session: date
    previous_session: date
    close: Decimal
    previous_close: Decimal

    def __post_init__(self) -> None:
        if self.previous_session >= self.session:
            raise ValuationError("Quote sessions are invalid.")
        _number(self.close, positive=True)
        _number(self.previous_close, positive=True)


@dataclass(frozen=True, repr=False)
class Valuation:
    market_value: Decimal
    acquisition_value: Decimal
    previous_value: Decimal

    @property
    def daily_change(self) -> Decimal:
        return self.market_value - self.previous_value

    @property
    def daily_change_percent(self) -> Decimal | None:
        if not self.previous_value:
            return None
        return self.daily_change / self.previous_value * 100

    @property
    def unrealized_gain(self) -> Decimal:
        return self.market_value - self.acquisition_value

    @property
    def unrealized_gain_percent(self) -> Decimal | None:
        if not self.acquisition_value:
            return None
        return self.unrealized_gain / self.acquisition_value * 100


@dataclass(frozen=True, repr=False)
class PortfolioValuation:
    rows: tuple[Valuation, ...]
    total: Valuation


def evaluate(
    holdings: Sequence[Holding],
    quotes: Mapping[str, Quote],
    *,
    session: date,
    previous_session: date,
) -> PortfolioValuation:
    """Fail the entire valuation if any price is missing or has wrong dates.

    Daily change compares the *current* quantities at both closing prices. It is
    price movement, not a cash-flow-adjusted return on yesterday's actual holdings.
    Percentages are unrounded; display formatting belongs to the notification layer.
    """
    if previous_session >= session:
        raise ValuationError("Requested sessions are invalid.")
    rows = []
    seen = set()
    for holding in holdings:
        key = (holding.symbol, holding.account)
        if key in seen:
            raise ValuationError("A holding row is duplicated.")
        seen.add(key)
        quote = quotes.get(holding.symbol)
        if quote is None:
            raise ValuationError("A required quote is unavailable.")
        if quote.session != session or quote.previous_session != previous_session:
            raise ValuationError("A quote does not match the requested sessions.")
        rows.append(
            Valuation(
                holding.quantity * quote.close,
                holding.quantity * holding.acquisition_price,
                holding.quantity * quote.previous_close,
            )
        )
    zero = Decimal(0)
    total = Valuation(
        sum((row.market_value for row in rows), zero),
        sum((row.acquisition_value for row in rows), zero),
        sum((row.previous_value for row in rows), zero),
    )
    return PortfolioValuation(tuple(rows), total)
