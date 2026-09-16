from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from euronext_pde.paths import ProjectPaths
from euronext_pde.providers.euronext_universe import (
    EuronextUniverseProvider,
)


def main() -> None:
    paths = ProjectPaths.discover()

    retrieved_at = datetime.now(UTC)

    as_of_date = retrieved_at.date()

    provider = EuronextUniverseProvider(
        page_size=2000,
    )

    result = provider.fetch(
        as_of_date=as_of_date,
    )

    snapshot_dir = paths.snapshots / as_of_date.isoformat()

    raw_dir = paths.raw / "euronext"

    snapshot_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    instruments = pd.DataFrame([item.model_dump() for item in result.instruments])

    observations = pd.DataFrame([item.model_dump() for item in result.observations])

    instruments.to_parquet(
        snapshot_dir / "universe.parquet",
        index=False,
    )

    observations.to_parquet(
        snapshot_dir / "universe_market_observations.parquet",
        index=False,
    )

    raw_payload = {
        "retrieved_at_utc": retrieved_at.isoformat(),
        "total_records": result.total_records,
        "pages": result.raw_pages,
    }

    (raw_dir / (f"universe_{as_of_date.isoformat()}.json")).write_text(
        json.dumps(
            raw_payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    duplicate_ids = int(instruments["instrument_id"].duplicated().sum())

    duplicate_isin_mic = int(
        instruments.duplicated(
            subset=[
                "isin",
                "mic",
            ]
        ).sum()
    )

    print("=" * 100)

    print("V1A2 — EURONEXT CORE UNIVERSE SNAPSHOT")

    print("=" * 100)

    print()

    print(
        "API total:",
        result.total_records,
    )

    print(
        "parsed instruments:",
        len(instruments),
    )

    print(
        "market observations:",
        len(observations),
    )

    print(
        "duplicate instrument_id:",
        duplicate_ids,
    )

    print(
        "duplicate ISIN/MIC:",
        duplicate_isin_mic,
    )

    print()

    print("MARKETS")

    print(
        instruments[
            [
                "mic",
                "market",
            ]
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print()

    print("MISSING MARKET DATA")

    print(
        observations[
            [
                "trading_currency",
                "last_price",
                "last_trade_at",
            ]
        ]
        .isna()
        .sum()
        .to_string()
    )

    print()

    print("PRICE DISTRIBUTION")

    print(
        observations["last_price"]
        .describe(
            percentiles=[
                0.01,
                0.05,
                0.10,
                0.25,
                0.50,
                0.75,
                0.90,
                0.95,
                0.99,
            ]
        )
        .to_string()
    )

    print()

    print("LOWEST NON-MISSING PRICES")

    low = (
        instruments[
            [
                "instrument_id",
                "company_name",
                "ticker",
                "mic",
            ]
        ]
        .merge(
            observations[
                [
                    "instrument_id",
                    "trading_currency",
                    "last_price",
                ]
            ],
            on="instrument_id",
            how="left",
        )
        .dropna(
            subset=[
                "last_price",
            ]
        )
        .sort_values("last_price")
        .head(25)
    )

    print(low.to_string(index=False))

    print()

    print(
        "SNAPSHOT:",
        snapshot_dir,
    )


if __name__ == "__main__":
    main()
