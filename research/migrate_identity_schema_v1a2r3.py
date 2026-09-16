from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from euronext_pde.identity import MIC_TO_MARKET
from euronext_pde.paths import ProjectPaths

URL_MIC_RE = re.compile(r"-([A-Z0-9]{4})/?$")


def extract_reference_mic(url: str) -> str:
    match = URL_MIC_RE.search(url)

    if match is None:
        raise ValueError(f"Could not extract reference MIC from {url}")

    return match.group(1)


def split_mics(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def latest_legacy_snapshot() -> Path:
    paths = ProjectPaths.discover()

    candidates = sorted(
        path
        for path in paths.snapshots.iterdir()
        if path.is_dir()
        and (path / "universe.parquet").is_file()
        and (path / "universe_market_observations.parquet").is_file()
    )

    if not candidates:
        raise RuntimeError("No legacy V1A2 snapshot available.")

    return candidates[-1]


def main() -> None:
    snapshot = latest_legacy_snapshot()

    legacy = pd.read_parquet(snapshot / "universe.parquet")

    legacy_observations = pd.read_parquet(snapshot / "universe_market_observations.parquet")

    legacy["reference_mic"] = legacy["product_url"].map(extract_reference_mic)

    legacy["security_id"] = legacy["isin"]

    legacy["trading_line_id"] = legacy["isin"] + "-" + legacy["reference_mic"]

    # --------------------------------------------------------
    # HARD INPUT GATES
    # --------------------------------------------------------

    if legacy["trading_line_id"].duplicated().any():
        raise RuntimeError("Trading line IDs are not unique.")

    if not legacy["reference_mic"].isin(MIC_TO_MARKET).all():
        raise RuntimeError("Unexpected reference MIC found.")

    # --------------------------------------------------------
    # SECURITIES
    # --------------------------------------------------------

    securities = legacy.groupby(
        "security_id",
        as_index=False,
    ).agg(
        as_of_date=("as_of_date", "max"),
        isin=("isin", "first"),
        active=("active", "any"),
        first_seen=("first_seen", "min"),
        last_seen=("last_seen", "max"),
        source=("source", "first"),
        source_url=("source_url", "first"),
    )

    securities = securities[
        [
            "as_of_date",
            "security_id",
            "isin",
            "active",
            "first_seen",
            "last_seen",
            "source",
            "source_url",
        ]
    ]

    # --------------------------------------------------------
    # TRADING LINES
    # --------------------------------------------------------

    trading_lines = legacy[
        [
            "as_of_date",
            "trading_line_id",
            "security_id",
            "ticker",
            "company_name",
            "reference_mic",
            "product_url",
            "active",
            "first_seen",
            "last_seen",
            "source",
            "source_url",
        ]
    ].copy()

    trading_lines = trading_lines.rename(
        columns={
            "company_name": "display_name",
        }
    )

    trading_lines["reference_market"] = trading_lines["reference_mic"].map(MIC_TO_MARKET)

    trading_lines = trading_lines[
        [
            "as_of_date",
            "trading_line_id",
            "security_id",
            "ticker",
            "display_name",
            "reference_mic",
            "reference_market",
            "product_url",
            "active",
            "first_seen",
            "last_seen",
            "source",
            "source_url",
        ]
    ]

    # --------------------------------------------------------
    # VENUE MEMBERSHIPS
    # --------------------------------------------------------

    membership_source = legacy[
        [
            "as_of_date",
            "security_id",
            "trading_line_id",
            "reference_mic",
            "mic",
        ]
    ].copy()

    membership_source["mic"] = membership_source["mic"].map(split_mics)

    memberships = membership_source.explode("mic").reset_index(drop=True)

    memberships["market"] = memberships["mic"].map(MIC_TO_MARKET)

    if memberships["market"].isna().any():
        raise RuntimeError("Unknown venue MIC found.")

    memberships["is_reference_venue"] = memberships["mic"] == memberships["reference_mic"]

    memberships["venue_membership_id"] = memberships["trading_line_id"] + "@" + memberships["mic"]

    venue_memberships = memberships[
        [
            "as_of_date",
            "venue_membership_id",
            "trading_line_id",
            "security_id",
            "mic",
            "market",
            "is_reference_venue",
        ]
    ].copy()

    # --------------------------------------------------------
    # MARKET OBSERVATIONS
    # Legacy observation key maps back to the legacy row.
    # --------------------------------------------------------

    line_map = legacy[
        [
            "instrument_id",
            "security_id",
            "trading_line_id",
            "reference_mic",
        ]
    ]

    observations = legacy_observations.merge(
        line_map,
        on="instrument_id",
        how="left",
        validate="one_to_one",
    )

    if observations["trading_line_id"].isna().any():
        raise RuntimeError("Failed to map legacy observation to trading line.")

    market_observations = observations[
        [
            "as_of_date",
            "trading_line_id",
            "security_id",
            "reference_mic",
            "trading_currency",
            "last_price",
            "day_change_pct",
            "last_trade_at",
        ]
    ].copy()

    # --------------------------------------------------------
    # FINAL HARD GATES
    # --------------------------------------------------------

    gates = {
        "security_id_unique": not securities["security_id"].duplicated().any(),
        "trading_line_id_unique": not trading_lines["trading_line_id"].duplicated().any(),
        "venue_membership_id_unique": not venue_memberships["venue_membership_id"]
        .duplicated()
        .any(),
        "observation_line_unique": not market_observations["trading_line_id"].duplicated().any(),
        "all_lines_have_security": trading_lines["security_id"]
        .isin(securities["security_id"])
        .all(),
        "all_memberships_have_line": venue_memberships["trading_line_id"]
        .isin(trading_lines["trading_line_id"])
        .all(),
        "all_lines_have_reference_membership": (
            venue_memberships[venue_memberships["is_reference_venue"]]["trading_line_id"].nunique()
            == len(trading_lines)
        ),
    }

    failed = [name for name, passed in gates.items() if not passed]

    if failed:
        raise RuntimeError(f"Canonical identity gates failed: {failed}")

    # Expected from the frozen R2 audit.
    expected_counts = {
        "securities": 1005,
        "trading_lines": 1011,
        "venue_memberships": 1040,
        "market_observations": 1011,
    }

    actual_counts = {
        "securities": len(securities),
        "trading_lines": len(trading_lines),
        "venue_memberships": len(venue_memberships),
        "market_observations": len(market_observations),
    }

    if actual_counts != expected_counts:
        raise RuntimeError(
            f"Unexpected canonical counts. Expected {expected_counts}, got {actual_counts}."
        )

    # --------------------------------------------------------
    # WRITE — separate canonical directory.
    # Never delete legacy evidence.
    # --------------------------------------------------------

    output = snapshot / "canonical"

    if output.exists():
        raise FileExistsError(f"Canonical output already exists: {output}")

    output.mkdir(
        parents=True,
        exist_ok=False,
    )

    securities.to_parquet(
        output / "securities.parquet",
        index=False,
    )

    trading_lines.to_parquet(
        output / "trading_lines.parquet",
        index=False,
    )

    venue_memberships.to_parquet(
        output / "venue_memberships.parquet",
        index=False,
    )

    market_observations.to_parquet(
        output / "market_observations.parquet",
        index=False,
    )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print("=" * 100)
    print("V1A2R3 — CANONICAL IDENTITY MIGRATION")
    print("=" * 100)

    print()
    print("SOURCE SNAPSHOT:", snapshot)
    print("OUTPUT:", output)

    print()
    print("SECURITIES:", len(securities))
    print("TRADING LINES:", len(trading_lines))
    print(
        "VENUE MEMBERSHIPS:",
        len(venue_memberships),
    )
    print(
        "MARKET OBSERVATIONS:",
        len(market_observations),
    )

    print()
    print("HARD GATES")

    for name, passed in gates.items():
        print(
            f"  {name:40s}",
            "PASS" if passed else "FAIL",
        )

    print()
    print("TRADING LINES BY REFERENCE MIC")
    print(trading_lines["reference_mic"].value_counts().sort_index().to_string())

    print()
    print("VENUE MEMBERSHIPS BY MIC")
    print(venue_memberships["mic"].value_counts().sort_index().to_string())

    print()
    print(
        "MULTI-LINE SECURITIES:",
        int(trading_lines["security_id"].value_counts().gt(1).sum()),
    )

    print()
    print("STATUS: PASS")


if __name__ == "__main__":
    main()
