from __future__ import annotations

import re

import pandas as pd

from euronext_pde.paths import ProjectPaths
from euronext_pde.providers.euronext_universe import COMPETITION_MICS

URL_MIC_RE = re.compile(r"-([A-Z0-9]{4})/?$")


def split_mics(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def extract_url_mic(url: str) -> str | None:
    match = URL_MIC_RE.search(url)

    if match is None:
        return None

    return match.group(1)


def main() -> None:
    paths = ProjectPaths.discover()

    snapshot_dirs = sorted(
        path
        for path in paths.snapshots.iterdir()
        if path.is_dir() and (path / "universe.parquet").is_file()
    )

    if not snapshot_dirs:
        raise RuntimeError("No universe snapshots found.")

    snapshot_dir = snapshot_dirs[-1]

    frame = pd.read_parquet(snapshot_dir / "universe.parquet")

    frame["mic_memberships"] = frame["mic"].map(split_mics)
    frame["membership_count"] = frame["mic_memberships"].map(len)
    frame["url_mic"] = frame["product_url"].map(extract_url_mic)

    multi = frame[frame["membership_count"] > 1].copy()

    total_memberships = int(frame["membership_count"].sum())

    duplicate_isin_mask = frame["isin"].duplicated(keep=False)

    duplicate_isins = frame[duplicate_isin_mask].sort_values(["isin", "mic", "ticker"])

    invalid_tokens: list[dict[str, str]] = []

    allowed = set(COMPETITION_MICS)

    for _, row in frame.iterrows():
        for mic in row["mic_memberships"]:
            if len(mic) != 4 or mic not in allowed:
                invalid_tokens.append(
                    {
                        "isin": row["isin"],
                        "ticker": row["ticker"],
                        "mic": mic,
                    }
                )

    url_mic_not_in_membership = frame[
        frame["url_mic"].notna()
        & ~frame.apply(
            lambda row: row["url_mic"] in row["mic_memberships"],
            axis=1,
        )
    ]

    print("=" * 100)
    print("V1A2R1 — UNIVERSE IDENTITY AUDIT")
    print("=" * 100)

    print()
    print("SNAPSHOT:", snapshot_dir)

    print()
    print("DIRECTORY ROWS:", len(frame))
    print("MARKET MEMBERSHIPS:", total_memberships)
    print("MULTI-MARKET ROWS:", len(multi))
    print(
        "EXTRA MEMBERSHIPS:",
        total_memberships - len(frame),
    )

    print()
    print("UNIQUE ISIN:", frame["isin"].nunique())
    print(
        "ROWS WITH REPEATED ISIN:",
        int(duplicate_isin_mask.sum()),
    )
    print(
        "REPEATED ISIN GROUPS:",
        int(duplicate_isins["isin"].nunique()),
    )

    print()
    print(
        "URL MIC MISSING:",
        int(frame["url_mic"].isna().sum()),
    )
    print(
        "URL MIC NOT IN DISPLAYED MEMBERSHIPS:",
        len(url_mic_not_in_membership),
    )

    print()
    print(
        "INVALID/UNEXPECTED MIC TOKENS:",
        len(invalid_tokens),
    )

    print()
    print("=" * 100)
    print("MULTI-MARKET ROWS")
    print("=" * 100)

    columns = [
        "company_name",
        "isin",
        "ticker",
        "mic",
        "url_mic",
        "market",
        "product_url",
    ]

    if multi.empty:
        print("NONE")
    else:
        print(multi[columns].sort_values(["isin", "ticker"]).to_string(index=False))

    print()
    print("=" * 100)
    print("REPEATED ISINS")
    print("=" * 100)

    if duplicate_isins.empty:
        print("NONE")
    else:
        print(duplicate_isins[columns].to_string(index=False))

    if not url_mic_not_in_membership.empty:
        print()
        print("=" * 100)
        print("URL MIC / MARKET MEMBERSHIP MISMATCH")
        print("=" * 100)

        print(url_mic_not_in_membership[columns].to_string(index=False))

    if invalid_tokens:
        print()
        print("=" * 100)
        print("INVALID MIC TOKENS")
        print("=" * 100)

        print(pd.DataFrame(invalid_tokens).to_string(index=False))


if __name__ == "__main__":
    main()
