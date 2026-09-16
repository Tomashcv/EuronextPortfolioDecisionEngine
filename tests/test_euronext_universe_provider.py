from datetime import date

from euronext_pde.providers.euronext_universe import (
    parse_row,
)


def test_parse_normal_equity_row() -> None:
    row = [
        (
            '<a href="/en/product/equities/'
            'BE0974293251-XBRU" '
            'data-order="AB INBEV" '
            'data-title-hover="AB INBEV">'
            "AB INBEV</a>"
        ),
        "BE0974293251",
        "ABI",
        ('<div class="nowrap pointer" title="Euronext Brussels">XBRU</div>'),
        (
            '<div class="text-right pd_currency_es">'
            "EUR "
            '<span class="pd_last_price_es">'
            "67.18</span></div>"
        ),
        (
            '<div class="text-right pd_percent">'
            '<span class="text-brand-kelly-green">'
            "0.06%</span></div>"
        ),
        (
            '<div class="text-right pointer tooltipDesign">'
            "11 Sep 2026"
            '<span class="tooltiptext">'
            "17:35 CEST</span></div>"
        ),
    ]

    instrument, observation = parse_row(
        row,
        as_of_date=date(2026, 9, 13),
    )

    assert instrument.instrument_id == "BE0974293251-XBRU"
    assert instrument.company_name == "AB INBEV"
    assert instrument.ticker == "ABI"
    assert instrument.mic == "XBRU"
    assert instrument.market == "Euronext Brussels"
    assert instrument.issue_type is None

    assert observation.trading_currency == "EUR"
    assert observation.last_price == 67.18
    assert observation.day_change_pct == 0.06
    assert observation.last_trade_at is not None
    assert observation.last_trade_at.year == 2026
    assert observation.last_trade_at.hour == 17


def test_parse_missing_market_data() -> None:
    row = [
        (
            '<a href="/en/product/equities/'
            'FR001400ZRT0-XPAR" '
            'data-order="AB SCIENCE BSA" '
            'data-title-hover="AB SCIENCE BSA">'
            "AB SCIENCE BSA</a>"
        ),
        "FR001400ZRT0",
        "ABBS",
        ('<div class="nowrap pointer" title="Euronext Paris">XPAR</div>'),
        '<div class="text-right pd_currency_es">-</div>',
        '<div class="text-right pd_percent">-</div>',
        ('<div class="text-right pointer tooltipDesign">-<span class="tooltiptext"></span></div>'),
    ]

    instrument, observation = parse_row(
        row,
        as_of_date=date(2026, 9, 13),
    )

    assert instrument.company_name == "AB SCIENCE BSA"
    assert instrument.issue_type is None
    assert observation.trading_currency is None
    assert observation.last_price is None
    assert observation.day_change_pct is None
    assert observation.last_trade_at is None
