from datetime import date

from euronext_pde.universe import (
    CANONICAL_UNIVERSE_COLUMNS,
    UniverseInstrument,
)


def test_canonical_universe_columns_are_unique() -> None:
    assert len(CANONICAL_UNIVERSE_COLUMNS) == len(set(CANONICAL_UNIVERSE_COLUMNS))


def test_universe_instrument_roundtrip() -> None:
    instrument = UniverseInstrument(
        as_of_date=date(2026, 9, 13),
        instrument_id="NL0000000001-XAMS",
        isin="NL0000000001",
        ticker="TEST",
        company_name="Test Company",
        mic="XAMS",
        market="Euronext Amsterdam",
        product_url=("https://live.euronext.com/en/product/equities/NL0000000001-XAMS"),
        first_seen=date(2026, 9, 13),
        last_seen=date(2026, 9, 13),
        source="test",
        source_url="https://example.com",
    )

    assert instrument.instrument_id == "NL0000000001-XAMS"
    assert instrument.ticker == "TEST"
    assert instrument.mic == "XAMS"
    assert instrument.active is True
    assert instrument.issue_type is None
