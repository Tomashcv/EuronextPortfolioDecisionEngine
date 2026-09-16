from __future__ import annotations

import csv
import io
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from euronext_pde.paths import ProjectPaths

SAMPLE_PER_MIC = 8

MICS = (
    "MTAA",
    "XAMS",
    "XBRU",
    "XLIS",
    "XMSM",
    "XOSL",
    "XPAR",
)

BASE_URL = "https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax"

OUTPUT = Path("research") / "v1b0d_cross_market_historical_coverage.tsv"


def latest_snapshot() -> Path:
    paths = ProjectPaths.discover()

    candidates = sorted(
        path
        for path in paths.snapshots.iterdir()
        if path.is_dir()
        and (path / "canonical" / "trading_lines.parquet").is_file()
        and (path / "canonical" / "instrument_classification.parquet").is_file()
    )

    if not candidates:
        raise RuntimeError("No canonical classified snapshot found.")

    return candidates[-1]


def deterministic_sample(
    frame: pd.DataFrame,
    count: int,
) -> pd.DataFrame:
    frame = frame.sort_values("trading_line_id").reset_index(drop=True)

    total = len(frame)

    if total <= count:
        return frame

    if count == 1:
        indices = [0]
    else:
        indices = sorted({round(index * (total - 1) / (count - 1)) for index in range(count)})

    return frame.iloc[indices].reset_index(drop=True)


def download(
    client: httpx.Client,
    trading_line_id: str,
) -> httpx.Response:
    url = f"{BASE_URL}/{trading_line_id}"

    referer = f"https://live.euronext.com/en/popout-page/getHistoricalPrice/{trading_line_id}"

    last_error: httpx.HTTPError | None = None

    for attempt in range(
        1,
        4,
    ):
        try:
            response = client.get(
                url,
                params={
                    "format": "csv",
                    "decimal_separator": ".",
                    "date_form": "d/m/Y",
                },
                headers={
                    "Referer": referer,
                },
                timeout=30.0,
            )

            response.raise_for_status()

            return response

        except httpx.HTTPError as exc:
            last_error = exc

            if attempt < 3:
                time.sleep(float(attempt))

    raise RuntimeError(f"Historical download failed for {trading_line_id}") from last_error


def parse_csv(
    text: str,
) -> tuple[
    str,
    list[dict[str, str]],
]:
    lines = [line for line in text.splitlines() if line.strip()]

    if len(lines) < 4:
        raise RuntimeError("Historical CSV is too short.")

    coverage_header = lines[1]

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[3:])),
        delimiter=";",
    )

    rows = list(reader)

    return (
        coverage_header,
        rows,
    )


def parse_day(
    value: str,
) -> date:
    day, month, year = (int(part) for part in value.split("/"))

    return date(
        year,
        month,
        day,
    )


def missing_count(
    rows: list[dict[str, str]],
    column: str,
) -> int:
    return sum(
        not str(
            row.get(
                column,
                "",
            )
        ).strip()
        for row in rows
    )


def main() -> None:
    snapshot = latest_snapshot()

    canonical = snapshot / "canonical"

    lines = pd.read_parquet(canonical / "trading_lines.parquet")

    classification = pd.read_parquet(canonical / "instrument_classification.parquet")

    common_ids = set(
        classification.loc[
            classification["is_common_stock"],
            "trading_line_id",
        ].astype(str)
    )

    universe = lines[lines["trading_line_id"].astype(str).isin(common_ids)].copy()

    samples: list[pd.DataFrame] = []

    print("=" * 100)
    print("V1B0D — CROSS-MARKET HISTORICAL COVERAGE AUDIT")
    print("=" * 100)

    for mic in MICS:
        subset = universe[universe["reference_mic"] == mic]

        sample = deterministic_sample(
            subset,
            SAMPLE_PER_MIC,
        )

        samples.append(sample)

        print(f"{mic}: population={len(subset)} sample={len(sample)}")

    sample_frame = pd.concat(
        samples,
        ignore_index=True,
    )

    observed_at = datetime.now(UTC)

    observed_date = observed_at.date()

    records: list[dict[str, Any]] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
    ) as client:
        total = len(sample_frame)

        for number, row in enumerate(
            sample_frame.itertuples(index=False),
            start=1,
        ):
            line_id = str(row.trading_line_id)

            print(
                f"[{number:02d}/{total:02d}] {row.reference_mic} {line_id} {row.display_name}",
                flush=True,
            )

            response = download(
                client,
                line_id,
            )

            (
                coverage_header,
                price_rows,
            ) = parse_csv(response.text)

            if price_rows:
                dates = [parse_day(item["Date"]) for item in price_rows]

                oldest = min(dates).date()

                newest = max(dates).date()

                duplicate_dates = len(dates) - len(set(dates))

                calendar_days = (newest - oldest).days

                age_days = (observed_date - newest).days

            else:
                oldest = None
                newest = None
                duplicate_dates = 0
                calendar_days = None
                age_days = None

            row_count = len(price_rows)

            record = {
                "observed_at_utc": observed_at.isoformat(),
                "trading_line_id": line_id,
                "security_id": str(row.security_id),
                "display_name": str(row.display_name),
                "ticker": str(row.ticker),
                "reference_mic": str(row.reference_mic),
                "coverage_header": coverage_header,
                "rows": row_count,
                "oldest": (oldest.isoformat() if oldest else None),
                "newest": (newest.isoformat() if newest else None),
                "calendar_days": calendar_days,
                "age_days": age_days,
                "duplicate_dates": duplicate_dates,
                "missing_open": missing_count(
                    price_rows,
                    "Open",
                ),
                "missing_high": missing_count(
                    price_rows,
                    "High",
                ),
                "missing_low": missing_count(
                    price_rows,
                    "Low",
                ),
                "missing_close": missing_count(
                    price_rows,
                    "Close",
                ),
                "missing_shares": missing_count(
                    price_rows,
                    "Number of Shares",
                ),
                "missing_trades": missing_count(
                    price_rows,
                    "Number of Trades",
                ),
                "missing_turnover": missing_count(
                    price_rows,
                    "Turnover",
                ),
                "missing_vwap": missing_count(
                    price_rows,
                    "vwap",
                ),
                "enough_60d": row_count >= 60,
                "enough_3m": row_count >= 63,
                "enough_6m": row_count >= 126,
                "enough_1y": row_count >= 252,
                "near_two_year_cap": (calendar_days is not None and calendar_days >= 700),
                "fresh": (age_days is not None and age_days <= 7),
            }

            records.append(record)

            time.sleep(0.20)

    result = pd.DataFrame(records)

    result.to_csv(
        OUTPUT,
        sep="\t",
        index=False,
    )

    print()
    print("=" * 100)
    print("SUMMARY BY MIC")
    print("=" * 100)

    for mic in MICS:
        frame = result[result["reference_mic"] == mic]

        print()
        print(mic)

        print(
            "  sampled:",
            len(frame),
        )

        print(
            "  fresh:",
            int(frame["fresh"].sum()),
        )

        print(
            "  enough 6m:",
            int(frame["enough_6m"].sum()),
        )

        print(
            "  enough 1y:",
            int(frame["enough_1y"].sum()),
        )

        print(
            "  near 2y cap:",
            int(frame["near_two_year_cap"].sum()),
        )

        print(
            "  rows min/median/max:",
            int(frame["rows"].min()),
            float(frame["rows"].median()),
            int(frame["rows"].max()),
        )

        print(
            "  stale:",
            int((~frame["fresh"]).sum()),
        )

    total_missing = int(
        result[
            [
                "missing_open",
                "missing_high",
                "missing_low",
                "missing_close",
            ]
        ]
        .sum()
        .sum()
    )

    print()
    print("=" * 100)
    print("GLOBAL")
    print("=" * 100)

    print(
        "SAMPLED LINES:",
        len(result),
    )

    print(
        "FRESH:",
        int(result["fresh"].sum()),
    )

    print(
        "ENOUGH 6M:",
        int(result["enough_6m"].sum()),
    )

    print(
        "ENOUGH 1Y:",
        int(result["enough_1y"].sum()),
    )

    print(
        "NEAR 2Y CAP:",
        int(result["near_two_year_cap"].sum()),
    )

    print(
        "DUPLICATE DATES:",
        int(result["duplicate_dates"].sum()),
    )

    print(
        "MISSING OHLC CELLS:",
        total_missing,
    )

    print()
    print(
        "WROTE:",
        OUTPUT,
    )


if __name__ == "__main__":
    main()
