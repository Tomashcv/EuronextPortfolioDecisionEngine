from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class UniverseInstrument(BaseModel):
    """Canonical point-in-time representation of one Euronext listing."""

    model_config = ConfigDict(extra="forbid")

    as_of_date: date

    instrument_id: str
    isin: str = Field(min_length=12, max_length=12)
    ticker: str = Field(min_length=1)
    company_name: str = Field(min_length=1)

    mic: str
    market: str
    product_url: str

    issuer_country: str | None = None
    issue_type: str | None = None

    industry: str | None = None
    supersector: str | None = None
    sector: str | None = None
    subsector: str | None = None

    capitalization_compartment: str | None = None

    active: bool = True

    first_seen: date
    last_seen: date

    source: str
    source_url: str


class UniverseMarketObservation(BaseModel):
    """Market-state observation returned with the product directory."""

    model_config = ConfigDict(extra="forbid")

    as_of_date: date
    instrument_id: str

    trading_currency: str | None = None
    last_price: float | None = None
    day_change_pct: float | None = None
    last_trade_at: datetime | None = None


CANONICAL_UNIVERSE_COLUMNS = [
    "as_of_date",
    "instrument_id",
    "isin",
    "ticker",
    "company_name",
    "mic",
    "market",
    "product_url",
    "issuer_country",
    "issue_type",
    "industry",
    "supersector",
    "sector",
    "subsector",
    "capitalization_compartment",
    "active",
    "first_seen",
    "last_seen",
    "source",
    "source_url",
]


MARKET_OBSERVATION_COLUMNS = [
    "as_of_date",
    "instrument_id",
    "trading_currency",
    "last_price",
    "day_change_pct",
    "last_trade_at",
]
