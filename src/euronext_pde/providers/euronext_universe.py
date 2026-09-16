from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from euronext_pde.universe import (
    UniverseInstrument,
    UniverseMarketObservation,
)

BASE_URL = "https://live.euronext.com"

REFERER = f"{BASE_URL}/en/products/equities/regulated/list"

ENDPOINT = f"{BASE_URL}/en/product_directory/data/stocks-euronext-regulated"


COMPETITION_MICS = (
    "MTAA",  # Milan
    "XAMS",  # Amsterdam
    "XBRU",  # Brussels
    "XLIS",  # Lisbon
    "XMSM",  # Dublin
    "XOSL",  # Oslo
    "XPAR",  # Paris
)


DISPLAY_POINTS = "name,isin,symbol,market,lastPrice,precentDayChange,lastTradeTime"


MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass(frozen=True)
class UniverseFetchResult:
    total_records: int
    instruments: list[UniverseInstrument]
    observations: list[UniverseMarketObservation]
    raw_pages: list[dict[str, object]]


def build_payload(
    *,
    start: int,
    length: int,
    draw: int,
) -> dict[str, str]:

    payload: dict[str, str] = {
        "draw": str(draw),
        "start": str(start),
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "0",
        "order[0][dir]": "asc",
        "args[display_datapoints]": DISPLAY_POINTS,
        "iDisplayLength": str(length),
        "iDisplayStart": str(start),
        "sSortDir_0": "asc",
        "sSortField": "shortName",
    }

    for i in range(7):
        payload[f"columns[{i}][data]"] = str(i)
        payload[f"columns[{i}][name]"] = ""
        payload[f"columns[{i}][searchable]"] = "true"
        payload[f"columns[{i}][orderable]"] = "true" if i == 0 else "false"
        payload[f"columns[{i}][search][value]"] = ""
        payload[f"columns[{i}][search][regex]"] = "false"

    return payload


def parse_name_fragment(
    fragment: str,
) -> tuple[str, str]:

    soup = BeautifulSoup(
        fragment,
        "html.parser",
    )

    anchor = soup.find("a")

    if anchor is None:
        raise ValueError(f"Could not parse product anchor: {fragment}")

    company_name = (
        anchor.get("data-title-hover")
        or anchor.get("data-order")
        or anchor.get_text(" ", strip=True)
    )

    href = anchor.get("href")

    if not href:
        raise ValueError(f"Product URL missing: {fragment}")

    return (
        str(company_name).strip(),
        urljoin(
            BASE_URL,
            str(href),
        ),
    )


def parse_market_fragment(
    fragment: str,
) -> tuple[str, str]:

    soup = BeautifulSoup(
        fragment,
        "html.parser",
    )

    node = soup.find()

    if node is None:
        raise ValueError(f"Could not parse market fragment: {fragment}")

    mic = node.get_text(
        " ",
        strip=True,
    )

    market = node.get("title") or mic

    return (
        mic.strip(),
        str(market).strip(),
    )


def parse_price_fragment(
    fragment: str,
) -> tuple[str | None, float | None]:

    soup = BeautifulSoup(
        fragment,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    if not text or text == "-":
        return None, None

    currency_match = re.search(
        r"\b[A-Z]{3}\b",
        text,
    )

    currency = currency_match.group(0) if currency_match else None

    price_node = soup.select_one(".pd_last_price_es")

    if price_node is None:
        return currency, None

    raw_price = price_node.get_text(strip=True).replace(",", "")

    try:
        price = float(raw_price)

    except ValueError:
        price = None

    return currency, price


def parse_change_fragment(
    fragment: str,
) -> float | None:

    soup = BeautifulSoup(
        fragment,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    if not text or text == "-":
        return None

    match = re.search(
        r"([-+]?\d+(?:\.\d+)?)%",
        text,
    )

    if not match:
        return None

    return float(match.group(1))


def parse_trade_time_fragment(
    fragment: str,
) -> datetime | None:

    soup = BeautifulSoup(
        fragment,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    if not text or text.startswith("-"):
        return None

    date_match = re.search(
        r"(\d{1,2}) "
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
        r"(\d{4})",
        text,
    )

    time_match = re.search(
        r"(\d{2}):(\d{2})",
        text,
    )

    if not date_match:
        return None

    day = int(date_match.group(1))

    month = MONTHS[date_match.group(2)]

    year = int(date_match.group(3))

    hour = int(time_match.group(1)) if time_match else 0

    minute = int(time_match.group(2)) if time_match else 0

    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo("Europe/Paris"),
    )


def parse_row(
    row: list[object],
    *,
    as_of_date: date,
) -> tuple[
    UniverseInstrument,
    UniverseMarketObservation,
]:

    if len(row) < 7:
        raise ValueError(f"Unexpected Euronext row length: {len(row)}")

    company_name, product_url = parse_name_fragment(str(row[0]))

    isin = str(row[1]).strip()

    ticker = str(row[2]).strip()

    mic, market = parse_market_fragment(str(row[3]))

    currency, last_price = parse_price_fragment(str(row[4]))

    day_change_pct = parse_change_fragment(str(row[5]))

    last_trade_at = parse_trade_time_fragment(str(row[6]))

    instrument_id = f"{isin}-{mic}"

    instrument = UniverseInstrument(
        as_of_date=as_of_date,
        instrument_id=instrument_id,
        isin=isin,
        ticker=ticker,
        company_name=company_name,
        mic=mic,
        market=market,
        product_url=product_url,
        issue_type=None,
        active=True,
        first_seen=as_of_date,
        last_seen=as_of_date,
        source="Euronext Live",
        source_url=ENDPOINT,
    )

    observation = UniverseMarketObservation(
        as_of_date=as_of_date,
        instrument_id=instrument_id,
        trading_currency=currency,
        last_price=last_price,
        day_change_pct=day_change_pct,
        last_trade_at=last_trade_at,
    )

    return instrument, observation


class EuronextUniverseProvider:
    """Direct provider for the Euronext regulated-equity directory."""

    def __init__(
        self,
        *,
        page_size: int = 2000,
    ) -> None:

        self.page_size = page_size

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/152 Safari/537.36"
            ),
            "Accept": ("application/json, text/javascript, */*; q=0.01"),
            "X-Requested-With": ("XMLHttpRequest"),
            "Referer": REFERER,
        }

    def fetch(
        self,
        *,
        as_of_date: date,
    ) -> UniverseFetchResult:

        raw_pages: list[dict[str, object]] = []

        raw_rows: list[list[object]] = []

        with httpx.Client(
            headers=self.headers,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            landing = client.get(REFERER)

            landing.raise_for_status()

            start = 0
            draw = 1
            total_records: int | None = None

            while total_records is None or start < total_records:
                response = client.post(
                    ENDPOINT,
                    params={
                        "mics": ",".join(COMPETITION_MICS),
                    },
                    data=build_payload(
                        start=start,
                        length=self.page_size,
                        draw=draw,
                    ),
                )

                response.raise_for_status()

                payload = response.json()

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise TypeError("Unexpected Euronext response type.")

                raw_pages.append(payload)

                total_records = int(payload["iTotalRecords"])

                page_rows = payload.get(
                    "aaData",
                    [],
                )

                if not isinstance(
                    page_rows,
                    list,
                ):
                    raise TypeError("Euronext aaData is not a list.")

                raw_rows.extend(page_rows)

                if not page_rows:
                    break

                start += len(page_rows)

                draw += 1

        if total_records is None:
            raise RuntimeError("No Euronext universe response received.")

        instruments: list[UniverseInstrument] = []

        observations: list[UniverseMarketObservation] = []

        for row in raw_rows:
            if not isinstance(
                row,
                list,
            ):
                raise TypeError("Unexpected Euronext row type.")

            instrument, observation = parse_row(
                row,
                as_of_date=as_of_date,
            )

            instruments.append(instrument)

            observations.append(observation)

        return UniverseFetchResult(
            total_records=total_records,
            instruments=instruments,
            observations=observations,
            raw_pages=raw_pages,
        )
