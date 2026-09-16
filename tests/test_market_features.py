from __future__ import annotations

from datetime import date, timedelta

import pytest

from euronext_pde.features.market import (
    compute_market_risk_features,
)
from euronext_pde.market_data import (
    AdjustmentBasis,
    DailyMarketObservation,
)


def make_rows(
    closes: list[float],
    *,
    trading_line_id: str = ("TEST000000001-XPAR"),
    provider: str = "test",
) -> list[DailyMarketObservation]:
    start = date(
        2025,
        1,
        1,
    )

    rows: list[DailyMarketObservation] = []

    for index, close in enumerate(closes):
        rows.append(
            DailyMarketObservation(
                trading_line_id=(trading_line_id),
                security_id=(trading_line_id.split("-")[0]),
                reference_mic=(trading_line_id.split("-")[-1]),
                provider=provider,
                provider_mic=(trading_line_id.split("-")[-1]),
                adjustment_basis=(AdjustmentBasis.PROVIDER_DEFAULT),
                session_date=(start + timedelta(days=index)),
                open=close,
                high=close,
                low=close,
                last=close,
                close=close,
                number_of_shares=(1000.0 + index),
                number_of_trades=(100.0 + index),
                turnover=(10_000.0 + index),
                vwap=close,
            )
        )

    return rows


def test_momentum_exact_windows() -> None:
    closes = [float(100 + index) for index in range(300)]

    features = compute_market_risk_features(make_rows(closes))

    assert features.momentum_1m == pytest.approx(closes[-1] / closes[-22] - 1.0)

    assert features.momentum_3m == pytest.approx(closes[-1] / closes[-64] - 1.0)

    assert features.momentum_6m == pytest.approx(closes[-1] / closes[-127] - 1.0)


def test_constant_price_has_zero_volatility() -> None:
    rows = make_rows([100.0] * 300)

    features = compute_market_risk_features(rows)

    assert features.volatility_60d_annualized == pytest.approx(0.0)

    assert features.current_drawdown_252d == pytest.approx(0.0)

    assert features.max_drawdown_252d == pytest.approx(0.0)


def test_drawdown_definitions() -> None:
    closes = [100.0] * 248 + [
        120.0,
        90.0,
        100.0,
        110.0,
    ]

    features = compute_market_risk_features(make_rows(closes))

    assert features.current_drawdown_252d == pytest.approx(110.0 / 120.0 - 1.0)

    assert features.max_drawdown_252d == pytest.approx(90.0 / 120.0 - 1.0)


def test_insufficient_history_is_explicit() -> None:
    features = compute_market_risk_features(make_rows([100.0] * 30))

    assert features.has_1m
    assert not features.has_3m
    assert not features.has_6m

    assert features.volatility_60d_annualized is None

    assert features.current_drawdown_252d is None

    assert features.max_drawdown_252d is None

    assert features.has_liquidity_20d


def test_liquidity_uses_median_tail() -> None:
    rows = make_rows([100.0] * 30)

    features = compute_market_risk_features(rows)

    expected_turnover = 10_019.5

    expected_trades = 119.5

    expected_shares = 1019.5

    assert features.median_turnover_20d == pytest.approx(expected_turnover)

    assert features.median_trades_20d == pytest.approx(expected_trades)

    assert features.median_shares_20d == pytest.approx(expected_shares)


def test_unsorted_input_is_normalized() -> None:
    rows = make_rows([float(100 + index) for index in range(300)])

    rows.reverse()

    features = compute_market_risk_features(rows)

    assert features.as_of_date == max(row.session_date for row in rows)

    assert features.has_6m


def test_duplicate_dates_fail_closed() -> None:
    rows = make_rows([100.0] * 30)

    rows.append(rows[-1])

    with pytest.raises(
        ValueError,
        match=("duplicate session dates"),
    ):
        compute_market_risk_features(rows)


def test_mixed_trading_lines_fail_closed() -> None:
    rows = make_rows([100.0] * 30)

    other = make_rows(
        [100.0],
        trading_line_id=("TEST000000002-XPAR"),
    )

    rows.extend(other)

    with pytest.raises(
        ValueError,
        match=("multiple trading lines"),
    ):
        compute_market_risk_features(rows)
