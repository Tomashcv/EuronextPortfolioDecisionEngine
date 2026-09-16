from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class Security(BaseModel):
    """Economic security identity.

    Fundamentals, growth and valuation belong at this level.
    """

    model_config = ConfigDict(extra="forbid")

    as_of_date: date

    security_id: str = Field(min_length=12, max_length=12)
    isin: str = Field(min_length=12, max_length=12)

    active: bool

    first_seen: date
    last_seen: date

    source: str
    source_url: str


class TradingLine(BaseModel):
    """Reference trading line exposed by the Euronext directory.

    Price-derived features belong at this level.
    """

    model_config = ConfigDict(extra="forbid")

    as_of_date: date

    trading_line_id: str
    security_id: str

    ticker: str
    display_name: str

    reference_mic: str = Field(min_length=4, max_length=4)
    reference_market: str

    product_url: str

    active: bool

    first_seen: date
    last_seen: date

    source: str
    source_url: str


class VenueMembership(BaseModel):
    """Venue membership of one trading line."""

    model_config = ConfigDict(extra="forbid")

    as_of_date: date

    venue_membership_id: str
    trading_line_id: str
    security_id: str

    mic: str = Field(min_length=4, max_length=4)
    market: str

    is_reference_venue: bool


class TradingLineMarketObservation(BaseModel):
    """Market observation associated with the reference trading line."""

    model_config = ConfigDict(extra="forbid")

    as_of_date: date

    trading_line_id: str
    security_id: str
    reference_mic: str = Field(min_length=4, max_length=4)

    trading_currency: str | None = None

    last_price: float | None = None
    day_change_pct: float | None = None
    last_trade_at: datetime | None = None


MIC_TO_MARKET = {
    "MTAA": "Euronext Milan",
    "XAMS": "Euronext Amsterdam",
    "XBRU": "Euronext Brussels",
    "XLIS": "Euronext Lisbon",
    "XMSM": "Euronext Dublin",
    "XOSL": "Oslo Børs",
    "XPAR": "Euronext Paris",
}
