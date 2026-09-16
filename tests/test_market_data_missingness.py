from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import httpx
import pytest

from euronext_pde.features.market import (
    compute_market_risk_features,
)
from euronext_pde.market_data import (
    AdjustmentBasis,
    DailyMarketObservation,
)
from euronext_pde.providers.historical_market_data import (
    NoHistoryError,
    RoutingHistoricalMarketDataProvider,
    parse_borsa_payload,
)


def make_complete_rows(
    count: int = 300,
) -> list[DailyMarketObservation]:
    start = date(
        2025,
        1,
        1,
    )

    return [
        DailyMarketObservation(
            trading_line_id=("TEST000000001-XPAR"),
            security_id=("TEST000000001"),
            reference_mic="XPAR",
            provider="test",
            provider_mic="XPAR",
            adjustment_basis=(AdjustmentBasis.PROVIDER_DEFAULT),
            session_date=(start + timedelta(days=index)),
            open=100.0,
            high=101.0,
            low=99.0,
            last=100.0,
            close=100.0,
            number_of_shares=1000.0,
            number_of_trades=100.0,
            turnover=100_000.0,
            vwap=100.0,
        )
        for index in range(count)
    ]


def test_borsa_missing_open_is_not_fatal() -> None:
    payload = {
        "transco": {
            "exchCode": "XMIL",
        },
        "history": {
            "historyDt": [
                {
                    "dt": "20230323",
                    "openPx": None,
                    "highPx": 3.94,
                    "lowPx": 3.94,
                    "lastPx": 3.94,
                    "closePx": 3.94,
                    "qty": 6.0,
                    "volNbTrade": 2.0,
                    "volCap": 23.64,
                    "vwap": 3.94,
                }
            ]
        },
    }

    rows = parse_borsa_payload(
        payload,
        trading_line_id=("IT0005481855-MTAA"),
        security_id=("IT0005481855"),
        reference_mic="MTAA",
        adjusted=True,
    )

    assert len(rows) == 1
    assert rows[0].open is None
    assert rows[0].close == 3.94


def test_borsa_missing_turnover_and_vwap_is_not_fatal() -> None:
    payload = {
        "transco": {
            "exchCode": "XMIL",
        },
        "history": {
            "historyDt": [
                {
                    "dt": "20241023",
                    "openPx": 20.0,
                    "highPx": 20.0,
                    "lowPx": 20.0,
                    "lastPx": 20.0,
                    "closePx": 20.0,
                    "qty": 0.00002,
                    "volNbTrade": 1.0,
                    "volCap": None,
                    "vwap": None,
                }
            ]
        },
    }

    rows = parse_borsa_payload(
        payload,
        trading_line_id=("IT0005730095-MTAA"),
        security_id=("IT0005730095"),
        reference_mic="MTAA",
        adjusted=True,
    )

    assert rows[0].close == 20.0
    assert rows[0].turnover is None
    assert rows[0].vwap is None


def test_old_missing_ancillary_fields_do_not_poison_recent_features() -> None:
    rows = make_complete_rows()

    rows[10] = replace(
        rows[10],
        open=None,
    )

    rows[20] = replace(
        rows[20],
        turnover=None,
        vwap=None,
    )

    features = compute_market_risk_features(rows)

    assert features.has_1m
    assert features.has_3m
    assert features.has_6m
    assert features.has_volatility_60d
    assert features.has_drawdown_252d
    assert features.has_liquidity_20d


def test_recent_missing_turnover_fails_only_liquidity_coverage() -> None:
    rows = make_complete_rows()

    rows[-5] = replace(
        rows[-5],
        turnover=None,
    )

    features = compute_market_risk_features(rows)

    assert features.has_6m
    assert features.has_volatility_60d
    assert features.has_drawdown_252d

    assert features.median_turnover_20d is None

    assert not features.has_liquidity_20d


def test_routing_provider_classifies_empty_history_as_no_history() -> None:
    body = (
        '\ufeff"Historical Data"\n'
        '"From  to "\n'
        "BMG455841020\n"
        "Date;Open;High;Low;Last;Close;"
        '"Number of Shares";'
        '"Number of Trades";Turnover\n'
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers={
                "content-type": "text/csv;charset=UTF-8",
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)

    with httpx.Client(
        transport=transport,
    ) as client:
        provider = RoutingHistoricalMarketDataProvider(client)

        with pytest.raises(
            NoHistoryError,
            match=("no historical observations"),
        ):
            provider.fetch(
                trading_line_id=("BMG455841020-XAMS"),
                security_id=("BMG455841020"),
                reference_mic="XAMS",
            )
