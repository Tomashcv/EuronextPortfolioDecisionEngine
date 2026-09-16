from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class AdjustmentBasis(StrEnum):
    """Meaning of historical price adjustment."""

    PROVIDER_DEFAULT = "provider_default"
    CORPORATE_ACTION_ADJUSTED = "corporate_action_adjusted"
    NON_ADJUSTED = "non_adjusted"


@dataclass(frozen=True, slots=True)
class DailyMarketObservation:
    """Canonical daily market observation for one trading line."""

    trading_line_id: str
    security_id: str
    reference_mic: str
    provider: str
    provider_mic: str
    adjustment_basis: AdjustmentBasis

    session_date: date

    # Close is the core field required by the current
    # return/risk feature layer.
    #
    # Other session fields may be absent at the source.
    open: float | None
    high: float | None
    low: float | None
    last: float | None
    close: float

    number_of_shares: float | None
    number_of_trades: float | None
    turnover: float | None
    vwap: float | None

    def __post_init__(self) -> None:
        if not self.trading_line_id:
            raise ValueError("trading_line_id cannot be empty.")

        if not self.security_id:
            raise ValueError("security_id cannot be empty.")

        if not self.reference_mic:
            raise ValueError("reference_mic cannot be empty.")

        if self.high is not None and self.low is not None and self.high < self.low:
            raise ValueError("high cannot be below low.")

        for name, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("last", self.last),
            ("close", self.close),
            (
                "number_of_shares",
                self.number_of_shares,
            ),
            (
                "number_of_trades",
                self.number_of_trades,
            ),
            ("turnover", self.turnover),
            ("vwap", self.vwap),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative.")
