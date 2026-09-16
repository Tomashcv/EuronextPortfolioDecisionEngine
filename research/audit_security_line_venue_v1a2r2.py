from __future__ import annotations

import re

import pandas as pd

from euronext_pde.paths import ProjectPaths

URL_MIC_RE = re.compile(r"-([A-Z0-9]{4})/?$")


def split_mics(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def extract_url_mic(url: str) -> str:
    match = URL_MIC_RE.search(url)

    if match is None:
        raise ValueError(f"Could not extract reference MIC from {url}")

    return match.group(1)


def main() -> None:
    paths = ProjectPaths.discover()

    snapshots = sorted(
        path
        for path in paths.snapshots.iterdir()
        if path.is_dir() and (path / "universe.parquet").is_file()
    )

    if not snapshots:
        raise RuntimeError("No universe snapshot found.")

    snapshot = snapshots[-1]

    frame = pd.read_parquet(snapshot / "universe.parquet")

    frame["security_id"] = frame["isin"]

    frame["reference_mic"] = frame["product_url"].map(extract_url_mic)

    frame["trading_line_id"] = frame["isin"] + "-" + frame["reference_mic"]

    frame["membership_mics"] = frame["mic"].map(split_mics)

    memberships = (
        frame[
            [
                "security_id",
                "trading_line_id",
                "ticker",
                "reference_mic",
                "membership_mics",
            ]
        ]
        .explode("membership_mics")
        .rename(
            columns={
                "membership_mics": "membership_mic",
            }
        )
        .reset_index(drop=True)
    )

    memberships["venue_membership_id"] = (
        memberships["trading_line_id"] + "@" + memberships["membership_mic"]
    )

    duplicate_line_ids = frame[frame["trading_line_id"].duplicated(keep=False)].sort_values(
        [
            "trading_line_id",
            "ticker",
        ]
    )

    duplicate_membership_ids = memberships[
        memberships["venue_membership_id"].duplicated(keep=False)
    ].sort_values("venue_membership_id")

    security_venue_duplicates = memberships[
        memberships.duplicated(
            subset=[
                "security_id",
                "membership_mic",
            ],
            keep=False,
        )
    ].sort_values(
        [
            "security_id",
            "membership_mic",
            "trading_line_id",
        ]
    )

    reference_not_first = frame[
        frame.apply(
            lambda row: row["reference_mic"] != row["membership_mics"][0],
            axis=1,
        )
    ]

    repeated_security = frame[frame["security_id"].duplicated(keep=False)].sort_values(
        [
            "security_id",
            "reference_mic",
        ]
    )

    print("=" * 100)
    print("V1A2R2 — SECURITY / TRADING LINE / VENUE AUDIT")
    print("=" * 100)

    print()
    print("SECURITIES:", frame["security_id"].nunique())
    print("TRADING LINES:", len(frame))
    print(
        "UNIQUE TRADING LINE IDs:",
        frame["trading_line_id"].nunique(),
    )
    print("VENUE MEMBERSHIPS:", len(memberships))

    print()
    print(
        "DUPLICATE TRADING LINE IDs:",
        len(duplicate_line_ids),
    )
    print(
        "DUPLICATE VENUE MEMBERSHIP IDs:",
        len(duplicate_membership_ids),
    )
    print(
        "DUPLICATE SECURITY+VENUE PAIRS:",
        len(security_venue_duplicates),
    )
    print(
        "REFERENCE MIC NOT FIRST:",
        len(reference_not_first),
    )

    print()
    print(
        "SECURITIES WITH >1 TRADING LINE:",
        repeated_security["security_id"].nunique(),
    )

    print()
    print("=" * 100)
    print("REPEATED SECURITY TRADING LINES")
    print("=" * 100)

    if repeated_security.empty:
        print("NONE")
    else:
        print(
            repeated_security[
                [
                    "security_id",
                    "company_name",
                    "ticker",
                    "reference_mic",
                    "mic",
                    "market",
                    "product_url",
                ]
            ].to_string(index=False)
        )

    print()
    print("=" * 100)
    print("SECURITY + VENUE COLLISIONS")
    print("=" * 100)

    if security_venue_duplicates.empty:
        print("NONE")
    else:
        print(security_venue_duplicates.to_string(index=False))

    print()
    print("=" * 100)
    print("DUPLICATE TRADING LINE IDs")
    print("=" * 100)

    if duplicate_line_ids.empty:
        print("NONE")
    else:
        print(
            duplicate_line_ids[
                [
                    "security_id",
                    "company_name",
                    "ticker",
                    "reference_mic",
                    "mic",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()
