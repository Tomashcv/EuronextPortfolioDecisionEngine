from datetime import date

import pytest
from pydantic import ValidationError

from euronext_pde.identity import (
    Security,
    TradingLine,
    VenueMembership,
)

DAY = date(2026, 9, 13)


def test_security_identity_is_isin() -> None:
    security = Security(
        as_of_date=DAY,
        security_id="NL0000226223",
        isin="NL0000226223",
        active=True,
        first_seen=DAY,
        last_seen=DAY,
        source="Euronext Live",
        source_url="https://example.com",
    )

    assert security.security_id == security.isin


def test_trading_line_identity_includes_reference_mic() -> None:
    line = TradingLine(
        as_of_date=DAY,
        trading_line_id="NL0000226223-XPAR",
        security_id="NL0000226223",
        ticker="STMPA",
        display_name="STMICROELECTRONICS",
        reference_mic="XPAR",
        reference_market="Euronext Paris",
        product_url=("https://live.euronext.com/en/product/equities/NL0000226223-XPAR"),
        active=True,
        first_seen=DAY,
        last_seen=DAY,
        source="Euronext Live",
        source_url="https://example.com",
    )

    assert line.trading_line_id == "NL0000226223-XPAR"


def test_venue_membership_is_distinct_from_trading_line() -> None:
    membership = VenueMembership(
        as_of_date=DAY,
        venue_membership_id="NL0006294274-XPAR@XAMS",
        trading_line_id="NL0006294274-XPAR",
        security_id="NL0006294274",
        mic="XAMS",
        market="Euronext Amsterdam",
        is_reference_venue=False,
    )

    assert membership.mic == "XAMS"
    assert membership.is_reference_venue is False


def test_mic_must_be_four_characters() -> None:
    with pytest.raises(ValidationError):
        VenueMembership(
            as_of_date=DAY,
            venue_membership_id="bad",
            trading_line_id="line",
            security_id="NL0006294274",
            mic="XPAR, XAMS",
            market="bad",
            is_reference_venue=False,
        )
