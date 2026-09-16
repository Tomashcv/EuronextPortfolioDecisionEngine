from __future__ import annotations

from euronext_pde.market_data import (
    AdjustmentBasis,
)
from euronext_pde.providers.historical_market_data import (
    parse_borsa_payload,
    parse_euronext_csv,
)


def test_parse_euronext_csv() -> None:
    text = """\
"Historical Data"
"From 01/09/2026 to 02/09/2026"
NL0000226223
Date;Open;High;Low;Last;Close;"Number of Shares";"Number of Trades";Turnover;vwap
02/09/2026;42.52;43.935;42.43;43.72;43.72;1790061;21953;77657394;43.3825
01/09/2026;43.485;44.155;41.83;42.305;42.305;2192052;30440;93238507;42.5348
"""

    rows = parse_euronext_csv(
        text,
        trading_line_id=("NL0000226223-XPAR"),
        security_id=("NL0000226223"),
        reference_mic="XPAR",
    )

    assert len(rows) == 2

    assert rows[0].session_date.isoformat() == "2026-09-01"

    assert rows[1].close == 43.72

    assert rows[0].adjustment_basis == AdjustmentBasis.PROVIDER_DEFAULT

    assert rows[0].provider_mic == "XPAR"


def test_parse_borsa_adjusted() -> None:
    payload = {
        "transco": {
            "code": "IT0003856405",
            "codification": "ISIN",
            "exchCode": "XMIL",
        },
        "history": {
            "historyDt": [
                {
                    "dt": "20260914",
                    "openPx": 49.9,
                    "closePx": 50.1,
                    "highPx": 50.5,
                    "lowPx": 49.885,
                    "lastPx": 50.1,
                    "qty": 45812.0,
                    "volNbTrade": 354.0,
                    "volCap": 2291400.345,
                    "vwap": 50.016,
                }
            ]
        },
    }

    rows = parse_borsa_payload(
        payload,
        trading_line_id=("IT0003856405-MTAA"),
        security_id=("IT0003856405"),
        reference_mic="MTAA",
        adjusted=True,
    )

    assert len(rows) == 1

    row = rows[0]

    assert row.session_date.isoformat() == "2026-09-14"

    assert row.provider_mic == "XMIL"

    assert row.adjustment_basis == AdjustmentBasis.CORPORATE_ACTION_ADJUSTED

    assert row.close == 50.1
    assert row.number_of_trades == 354.0


def test_parse_borsa_non_adjusted() -> None:
    payload = {
        "transco": {
            "exchCode": "XMIL",
        },
        "history": {
            "historyDt": [
                {
                    "dt": "20260914",
                    "openPx": 10.0,
                    "highPx": 11.0,
                    "lowPx": 9.0,
                    "lastPx": 10.5,
                    "closePx": 10.5,
                    "qty": 100.0,
                    "volNbTrade": 5.0,
                    "volCap": 1050.0,
                    "vwap": 10.5,
                }
            ]
        },
    }

    rows = parse_borsa_payload(
        payload,
        trading_line_id=("IT0000000000-MTAA"),
        security_id=("IT0000000000"),
        reference_mic="MTAA",
        adjusted=False,
    )

    assert rows[0].adjustment_basis == AdjustmentBasis.NON_ADJUSTED


def test_parsers_sort_ascending() -> None:
    payload = {
        "transco": {
            "exchCode": "XMIL",
        },
        "history": {
            "historyDt": [
                {
                    "dt": "20260914",
                    "openPx": 2,
                    "highPx": 2,
                    "lowPx": 2,
                    "lastPx": 2,
                    "closePx": 2,
                    "qty": 2,
                    "volNbTrade": 2,
                    "volCap": 2,
                    "vwap": 2,
                },
                {
                    "dt": "20260911",
                    "openPx": 1,
                    "highPx": 1,
                    "lowPx": 1,
                    "lastPx": 1,
                    "closePx": 1,
                    "qty": 1,
                    "volNbTrade": 1,
                    "volCap": 1,
                    "vwap": 1,
                },
            ]
        },
    }

    rows = parse_borsa_payload(
        payload,
        trading_line_id=("IT0000000000-MTAA"),
        security_id=("IT0000000000"),
        reference_mic="MTAA",
        adjusted=True,
    )

    assert rows[0].session_date.isoformat() == "2026-09-11"

    assert rows[-1].session_date.isoformat() == "2026-09-14"
