from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx


@dataclass(frozen=True)
class Probe:
    label: str
    trading_line_id: str


PROBES = (
    Probe(
        "Paris — STMicroelectronics",
        "NL0000226223-XPAR",
    ),
    Probe(
        "Milan — STMicroelectronics",
        "NL0000226223-MTAA",
    ),
    Probe(
        "Amsterdam — ING",
        "NL0011821202-XAMS",
    ),
    Probe(
        "Brussels — AB InBev",
        "BE0974293251-XBRU",
    ),
    Probe(
        "Lisbon — Euronext",
        "NL0006294274-XLIS",
    ),
    Probe(
        "Oslo — CMB.TECH",
        "BE0003816338-XOSL",
    ),
    Probe(
        "Dublin — placeholder",
        "",
    ),
)

BASE = "https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax"

OUTPUT = Path("research") / "v1b0c_euronext_historical_coverage_audit.txt"


def parse_date(
    value: str,
) -> date:
    day, month, year = (int(part) for part in value.split("/"))

    return date(
        year,
        month,
        day,
    )


def download(
    client: httpx.Client,
    trading_line_id: str,
) -> httpx.Response:
    response = client.get(
        f"{BASE}/{trading_line_id}",
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
    )

    response.raise_for_status()

    return response


def parse_csv(
    text: str,
) -> tuple[
    str,
    str,
    list[str],
    list[dict[str, str]],
]:
    lines = [line for line in text.splitlines() if line.strip()]

    if len(lines) < 5:
        raise RuntimeError("Historical CSV is unexpectedly short.")

    title = lines[0]
    coverage = lines[1]

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[3:])),
        delimiter=";",
    )

    rows = list(reader)

    if reader.fieldnames is None:
        raise RuntimeError("CSV has no columns.")

    return (
        title,
        coverage,
        reader.fieldnames,
        rows,
    )


def missing_count(
    rows: list[dict[str, str]],
    column: str,
) -> int:
    return sum(
        1
        for row in rows
        if not str(
            row.get(
                column,
                "",
            )
        ).strip()
    )


def main() -> None:
    probes = [probe for probe in PROBES if probe.trading_line_id]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
    }

    report: list[str] = []

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        for probe in probes:
            response = download(
                client,
                probe.trading_line_id,
            )

            (
                _title,
                coverage,
                columns,
                rows,
            ) = parse_csv(response.text)

            dates = [parse_date(row["Date"]) for row in rows]

            unique_dates = set(dates)

            duplicates = len(dates) - len(unique_dates)

            newest = max(dates)

            oldest = min(dates)

            calendar_days = (newest - oldest).days

            missing = {
                column: missing_count(
                    rows,
                    column,
                )
                for column in (
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Number of Shares",
                    "Number of Trades",
                    "Turnover",
                    "vwap",
                )
            }

            block = [
                "=" * 100,
                probe.label,
                probe.trading_line_id,
                f"HTTP: {response.status_code}",
                f"CONTENT-TYPE: {response.headers.get('content-type')}",
                f"COVERAGE HEADER: {coverage}",
                f"ROWS: {len(rows)}",
                f"OLDEST: {oldest.date().isoformat()}",
                f"NEWEST: {newest.date().isoformat()}",
                f"CALENDAR DAYS: {calendar_days}",
                f"DUPLICATE DATES: {duplicates}",
                f"COLUMNS: {columns}",
                "MISSING:",
            ]

            for key, value in missing.items():
                block.append(f"  {key:20s} {value}")

            report.extend(block)

            for line in block:
                print(line)

    OUTPUT.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "WROTE:",
        OUTPUT,
    )


if __name__ == "__main__":
    main()
