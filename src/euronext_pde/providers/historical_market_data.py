from __future__ import annotations

import csv
import io
import re
import time
from datetime import date
from typing import Any

import httpx

from euronext_pde.market_data import (
    AdjustmentBasis,
    DailyMarketObservation,
)

EURONEXT_PROVIDER = "euronext_full_download_csv"
BORSA_PROVIDER = "borsa_italiana_chart_api"

EURONEXT_BASE = "https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax"

BORSA_BASE = "https://grafici.borsaitaliana.it/api/instruments"

TOKEN_PATTERN = re.compile(r'token="([^"]+)"')


class NoHistoryError(RuntimeError):
    """The official provider returned no historical observations."""


def _parse_euronext_date(
    value: str,
) -> date:
    day, month, year = (int(part) for part in value.split("/"))

    return date(
        year,
        month,
        day,
    )


def _parse_borsa_date(
    value: str,
) -> date:
    if len(value) != 8:
        raise ValueError(f"Unexpected Borsa date: {value!r}")

    return date(
        int(value[0:4]),
        int(value[4:6]),
        int(value[6:8]),
    )


def _as_float(
    value: Any,
    *,
    field: str,
) -> float:
    if value is None:
        raise ValueError(f"Missing {field}.")

    text = str(value).strip()

    if not text:
        raise ValueError(f"Missing {field}.")

    return float(text)


def _as_optional_float(
    value: Any,
) -> float | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return float(text)


def parse_euronext_csv(
    text: str,
    *,
    trading_line_id: str,
    security_id: str,
    reference_mic: str,
) -> list[DailyMarketObservation]:
    lines = [line for line in text.splitlines() if line.strip()]

    if len(lines) < 4:
        raise ValueError("Euronext historical CSV is too short.")

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[3:])),
        delimiter=";",
    )

    observations: list[DailyMarketObservation] = []

    for row in reader:
        observations.append(
            DailyMarketObservation(
                trading_line_id=(trading_line_id),
                security_id=security_id,
                reference_mic=(reference_mic),
                provider=(EURONEXT_PROVIDER),
                provider_mic=(reference_mic),
                adjustment_basis=(AdjustmentBasis.PROVIDER_DEFAULT),
                session_date=(_parse_euronext_date(row["Date"])),
                open=_as_optional_float(row.get("Open")),
                high=_as_optional_float(row.get("High")),
                low=_as_optional_float(row.get("Low")),
                last=_as_optional_float(row.get("Last")),
                close=_as_float(
                    row.get("Close"),
                    field="Close",
                ),
                number_of_shares=(_as_optional_float(row.get("Number of Shares"))),
                number_of_trades=(_as_optional_float(row.get("Number of Trades"))),
                turnover=(_as_optional_float(row.get("Turnover"))),
                vwap=(_as_optional_float(row.get("vwap"))),
            )
        )

    observations.sort(key=lambda item: item.session_date)

    return observations


def parse_borsa_payload(
    payload: dict[str, Any],
    *,
    trading_line_id: str,
    security_id: str,
    reference_mic: str,
    adjusted: bool,
) -> list[DailyMarketObservation]:
    transco = payload.get("transco")

    history = payload.get("history")

    if not isinstance(
        transco,
        dict,
    ):
        raise TypeError("Missing Borsa transco.")

    if not isinstance(
        history,
        dict,
    ):
        raise TypeError("Missing Borsa history.")

    rows = history.get("historyDt")

    if not isinstance(
        rows,
        list,
    ):
        raise TypeError("Missing Borsa historyDt.")

    provider_mic = str(
        transco.get(
            "exchCode",
            "",
        )
    )

    if provider_mic != "XMIL":
        raise ValueError(f"Unexpected Borsa provider MIC: {provider_mic!r}")

    basis = AdjustmentBasis.CORPORATE_ACTION_ADJUSTED if adjusted else AdjustmentBasis.NON_ADJUSTED

    observations: list[DailyMarketObservation] = []

    for row in rows:
        if not isinstance(
            row,
            dict,
        ):
            raise TypeError("Invalid Borsa history row.")

        observations.append(
            DailyMarketObservation(
                trading_line_id=(trading_line_id),
                security_id=security_id,
                reference_mic=(reference_mic),
                provider=BORSA_PROVIDER,
                provider_mic=(provider_mic),
                adjustment_basis=basis,
                session_date=(_parse_borsa_date(str(row["dt"]))),
                open=_as_optional_float(row.get("openPx")),
                high=_as_optional_float(row.get("highPx")),
                low=_as_optional_float(row.get("lowPx")),
                last=_as_optional_float(row.get("lastPx")),
                close=_as_float(
                    row.get("closePx"),
                    field="closePx",
                ),
                number_of_shares=(_as_optional_float(row.get("qty"))),
                number_of_trades=(_as_optional_float(row.get("volNbTrade"))),
                turnover=(_as_optional_float(row.get("volCap"))),
                vwap=(_as_optional_float(row.get("vwap"))),
            )
        )

    observations.sort(key=lambda item: item.session_date)

    return observations


class EuronextHistoricalCsvProvider:
    def __init__(
        self,
        client: httpx.Client,
    ) -> None:
        self._client = client

    def fetch(
        self,
        *,
        trading_line_id: str,
        security_id: str,
        reference_mic: str,
    ) -> list[DailyMarketObservation]:
        response = self._client.get(
            (f"{EURONEXT_BASE}/{trading_line_id}"),
            params={
                "format": "csv",
                "decimal_separator": ".",
                "date_form": "d/m/Y",
            },
            headers={
                "Referer": (
                    f"https://live.euronext.com/en/popout-page/getHistoricalPrice/{trading_line_id}"
                ),
            },
            timeout=30.0,
        )

        response.raise_for_status()

        return parse_euronext_csv(
            response.text,
            trading_line_id=(trading_line_id),
            security_id=security_id,
            reference_mic=reference_mic,
        )


class BorsaItalianaHistoricalProvider:
    def __init__(
        self,
        client: httpx.Client,
    ) -> None:
        self._client = client

    def _token(
        self,
        *,
        security_id: str,
    ) -> str:
        chart_url = f"https://grafici.borsaitaliana.it/interactive-chart/{security_id}-XMIL?lang=it"

        response = self._client.get(
            chart_url,
            timeout=30.0,
        )

        response.raise_for_status()

        match = TOKEN_PATTERN.search(response.text)

        if match is None:
            raise RuntimeError(f"Borsa anonymous JWT not found for {security_id}.")

        return match.group(1)

    def fetch(
        self,
        *,
        trading_line_id: str,
        security_id: str,
        reference_mic: str,
        adjusted: bool = True,
        period: str = "5Y",
    ) -> list[DailyMarketObservation]:
        if reference_mic != "MTAA":
            raise ValueError("Borsa provider currently supports canonical MTAA only.")

        token = self._token(security_id=security_id)

        chart_url = f"https://grafici.borsaitaliana.it/interactive-chart/{security_id}-XMIL?lang=it"

        url = f"{BORSA_BASE}/{security_id},XMIL,ISIN/history/period"

        last_error: httpx.HTTPError | None = None

        for attempt in range(
            1,
            4,
        ):
            try:
                response = self._client.get(
                    url,
                    params={
                        "period": period,
                        "adjustment": ("true" if adjusted else "false"),
                        "add-last-price": "true",
                    },
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                        "Referer": chart_url,
                    },
                    timeout=30.0,
                )

                response.raise_for_status()

                payload = response.json()

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise TypeError("Unexpected Borsa response payload.")

                return parse_borsa_payload(
                    payload,
                    trading_line_id=(trading_line_id),
                    security_id=(security_id),
                    reference_mic=(reference_mic),
                    adjusted=adjusted,
                )

            except httpx.HTTPError as exc:
                last_error = exc

                if attempt < 3:
                    time.sleep(float(attempt))

        raise RuntimeError(f"Borsa historical request failed for {security_id}.") from last_error


class RoutingHistoricalMarketDataProvider:
    """Route canonical trading lines to the correct official source."""

    def __init__(
        self,
        client: httpx.Client,
    ) -> None:
        self._euronext = EuronextHistoricalCsvProvider(client)

        self._borsa = BorsaItalianaHistoricalProvider(client)

    def fetch(
        self,
        *,
        trading_line_id: str,
        security_id: str,
        reference_mic: str,
    ) -> list[DailyMarketObservation]:
        if reference_mic == "MTAA":
            observations = self._borsa.fetch(
                trading_line_id=(trading_line_id),
                security_id=security_id,
                reference_mic=(reference_mic),
                adjusted=True,
                period="5Y",
            )

        else:
            observations = self._euronext.fetch(
                trading_line_id=(trading_line_id),
                security_id=security_id,
                reference_mic=(reference_mic),
            )

        if not observations:
            raise NoHistoryError(
                f"Official provider returned no historical observations for {trading_line_id}."
            )

        return observations
