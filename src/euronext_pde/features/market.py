from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from euronext_pde.market_data import (
    AdjustmentBasis,
    DailyMarketObservation,
)

TRADING_DAYS_PER_YEAR = 252

MOMENTUM_1M_SESSIONS = 21
MOMENTUM_3M_SESSIONS = 63
MOMENTUM_6M_SESSIONS = 126

VOLATILITY_SESSIONS = 60
DRAWDOWN_SESSIONS = 252
LIQUIDITY_SESSIONS = 20


@dataclass(
    frozen=True,
    slots=True,
)
class MarketRiskFeatures:
    trading_line_id: str
    security_id: str
    reference_mic: str

    provider: str
    provider_mic: str
    adjustment_basis: AdjustmentBasis

    as_of_date: date
    available_sessions: int

    momentum_1m: float | None
    momentum_3m: float | None
    momentum_6m: float | None

    volatility_60d_annualized: float | None

    current_drawdown_252d: float | None
    max_drawdown_252d: float | None

    median_shares_20d: float | None
    median_trades_20d: float | None
    median_turnover_20d: float | None
    median_vwap_20d: float | None

    has_1m: bool
    has_3m: bool
    has_6m: bool
    has_volatility_60d: bool
    has_drawdown_252d: bool
    has_liquidity_20d: bool


def _validate_series(
    observations: list[DailyMarketObservation],
) -> list[DailyMarketObservation]:
    if not observations:
        raise ValueError("Market observation series cannot be empty.")

    rows = sorted(
        observations,
        key=lambda row: row.session_date,
    )

    first = rows[0]

    for row in rows:
        if row.trading_line_id != first.trading_line_id:
            raise ValueError("Series contains multiple trading lines.")

        if row.security_id != first.security_id:
            raise ValueError("Series contains multiple securities.")

        if row.reference_mic != first.reference_mic:
            raise ValueError("Series contains multiple reference MICs.")

        if row.provider != first.provider:
            raise ValueError("Series contains multiple providers.")

        if row.provider_mic != first.provider_mic:
            raise ValueError("Series contains multiple provider MICs.")

        if row.adjustment_basis != first.adjustment_basis:
            raise ValueError("Series contains mixed adjustment bases.")

    dates = [row.session_date for row in rows]

    if len(dates) != len(set(dates)):
        raise ValueError("Series contains duplicate session dates.")

    return rows


def _momentum(
    closes: list[float],
    sessions: int,
) -> float | None:
    if len(closes) < (sessions + 1):
        return None

    previous = closes[-(sessions + 1)]

    latest = closes[-1]

    if previous <= 0:
        return None

    return latest / previous - 1.0


def _simple_returns(
    closes: list[float],
) -> list[float]:
    returns: list[float] = []

    for previous, current in pairwise(closes):
        if previous <= 0:
            raise ValueError("Close must be positive to calculate returns.")

        returns.append(current / previous - 1.0)

    return returns


def _annualized_volatility(
    closes: list[float],
    sessions: int,
) -> float | None:
    if len(closes) < (sessions + 1):
        return None

    window = closes[-(sessions + 1) :]

    returns = _simple_returns(window)

    if len(returns) < 2:
        return None

    return statistics.stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _drawdowns(
    closes: list[float],
    sessions: int,
) -> tuple[
    float | None,
    float | None,
]:
    if len(closes) < sessions:
        return (
            None,
            None,
        )

    window = closes[-sessions:]

    peak = window[0]

    if peak <= 0:
        raise ValueError("Close must be positive to calculate drawdown.")

    max_drawdown = 0.0

    for close in window:
        if close <= 0:
            raise ValueError("Close must be positive to calculate drawdown.")

        peak = max(
            peak,
            close,
        )

        drawdown = close / peak - 1.0

        max_drawdown = min(
            max_drawdown,
            drawdown,
        )

    trailing_peak = max(window)

    current_drawdown = window[-1] / trailing_peak - 1.0

    return (
        current_drawdown,
        max_drawdown,
    )


def _median_tail(
    values: list[float | None],
    sessions: int,
) -> float | None:
    if len(values) < sessions:
        return None

    window = values[-sessions:]

    complete = [value for value in window if value is not None]

    if len(complete) != sessions:
        return None

    return float(statistics.median(complete))


def compute_market_risk_features(
    observations: list[DailyMarketObservation],
) -> MarketRiskFeatures:
    rows = _validate_series(observations)

    first = rows[0]
    latest = rows[-1]

    closes = [row.close for row in rows]

    shares = [row.number_of_shares for row in rows]

    trades = [row.number_of_trades for row in rows]

    turnover = [row.turnover for row in rows]

    vwaps = [row.vwap for row in rows]

    momentum_1m = _momentum(
        closes,
        MOMENTUM_1M_SESSIONS,
    )

    momentum_3m = _momentum(
        closes,
        MOMENTUM_3M_SESSIONS,
    )

    momentum_6m = _momentum(
        closes,
        MOMENTUM_6M_SESSIONS,
    )

    volatility = _annualized_volatility(
        closes,
        VOLATILITY_SESSIONS,
    )

    (
        current_drawdown,
        max_drawdown,
    ) = _drawdowns(
        closes,
        DRAWDOWN_SESSIONS,
    )

    median_shares = _median_tail(
        shares,
        LIQUIDITY_SESSIONS,
    )

    median_trades = _median_tail(
        trades,
        LIQUIDITY_SESSIONS,
    )

    median_turnover = _median_tail(
        turnover,
        LIQUIDITY_SESSIONS,
    )

    median_vwap = _median_tail(
        vwaps,
        LIQUIDITY_SESSIONS,
    )

    return MarketRiskFeatures(
        trading_line_id=(first.trading_line_id),
        security_id=(first.security_id),
        reference_mic=(first.reference_mic),
        provider=first.provider,
        provider_mic=(first.provider_mic),
        adjustment_basis=(first.adjustment_basis),
        as_of_date=(latest.session_date),
        available_sessions=len(rows),
        momentum_1m=(momentum_1m),
        momentum_3m=(momentum_3m),
        momentum_6m=(momentum_6m),
        volatility_60d_annualized=(volatility),
        current_drawdown_252d=(current_drawdown),
        max_drawdown_252d=(max_drawdown),
        median_shares_20d=(median_shares),
        median_trades_20d=(median_trades),
        median_turnover_20d=(median_turnover),
        median_vwap_20d=(median_vwap),
        has_1m=(momentum_1m is not None),
        has_3m=(momentum_3m is not None),
        has_6m=(momentum_6m is not None),
        has_volatility_60d=(volatility is not None),
        has_drawdown_252d=(current_drawdown is not None and max_drawdown is not None),
        has_liquidity_20d=(
            median_turnover is not None and median_trades is not None and median_shares is not None
        ),
    )
