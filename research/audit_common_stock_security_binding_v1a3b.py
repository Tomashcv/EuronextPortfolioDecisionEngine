from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from euronext_pde.paths import ProjectPaths
from euronext_pde.providers.euronext_universe import (
    COMPETITION_MICS,
    ENDPOINT,
    REFERER,
    build_payload,
    parse_name_fragment,
)

COMMON_STOCK_ISSUE_TYPE = "101"

URL_MIC_RE = re.compile(r"-([A-Z0-9]{4})/?$")

OUTPUT = Path("research") / "v1a3b_common_stock_security_binding_audit.json"


def latest_canonical_snapshot() -> Path:
    paths = ProjectPaths.discover()

    candidates = sorted(
        path
        for path in paths.snapshots.iterdir()
        if path.is_dir() and (path / "canonical" / "trading_lines.parquet").is_file()
    )

    if not candidates:
        raise RuntimeError("No canonical snapshot found.")

    return candidates[-1]


def fetch_directory(
    client: httpx.Client,
    *,
    common_stock_only: bool,
) -> dict[str, Any]:
    payload = build_payload(
        start=0,
        length=2000,
        draw=1,
    )

    if common_stock_only:
        payload["args[issueType]"] = COMMON_STOCK_ISSUE_TYPE

        payload["args[initialLetter]"] = ""

    response = client.post(
        ENDPOINT,
        params={
            "mics": ",".join(COMPETITION_MICS),
        },
        data=payload,
        headers={
            "Referer": REFERER,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    response.raise_for_status()

    result = response.json()

    if not isinstance(
        result,
        dict,
    ):
        raise TypeError("Unexpected directory response.")

    return result


def directory_rows(
    payload: dict[str, Any],
) -> list[list[Any]]:
    value = payload.get(
        "aaData",
        [],
    )

    if not isinstance(
        value,
        list,
    ):
        raise TypeError("aaData is not a list.")

    rows: list[list[Any]] = []

    for row in value:
        if not isinstance(
            row,
            list,
        ):
            raise TypeError("Directory row is not a list.")

        rows.append(row)

    return rows


def trading_line_id_from_row(
    row: list[Any],
) -> str:
    isin = str(row[1]).strip()

    _, product_url = parse_name_fragment(str(row[0]))

    match = URL_MIC_RE.search(product_url)

    if match is None:
        raise RuntimeError(f"Could not extract reference MIC from {product_url}")

    reference_mic = match.group(1)

    return f"{isin}-{reference_mic}"


def row_description(
    row: list[Any],
) -> dict[str, str]:
    name, product_url = parse_name_fragment(str(row[0]))

    return {
        "trading_line_id": trading_line_id_from_row(row),
        "company_name": name,
        "isin": str(row[1]).strip(),
        "ticker": str(row[2]).strip(),
        "product_url": product_url,
    }


def main() -> None:
    snapshot = latest_canonical_snapshot()

    trading_lines_path = snapshot / "canonical" / "trading_lines.parquet"

    trading_lines = pd.read_parquet(trading_lines_path)

    snapshot_ids = set(trading_lines["trading_line_id"].astype(str))

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
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        raw_payload = fetch_directory(
            client,
            common_stock_only=False,
        )

        common_payload = fetch_directory(
            client,
            common_stock_only=True,
        )

    raw_rows = directory_rows(raw_payload)

    common_rows = directory_rows(common_payload)

    raw_map = {trading_line_id_from_row(row): row for row in raw_rows}

    common_map = {trading_line_id_from_row(row): row for row in common_rows}

    raw_ids = set(raw_map)
    common_ids = set(common_map)

    live_added_vs_snapshot = sorted(raw_ids - snapshot_ids)

    live_missing_vs_snapshot = sorted(snapshot_ids - raw_ids)

    # --------------------------------------------------------
    # POINT-IN-TIME BINDING GATE
    # --------------------------------------------------------

    exact_snapshot_match = not live_added_vs_snapshot and not live_missing_vs_snapshot

    print("=" * 100)
    print("V1A3B — COMMON STOCK SECURITY BINDING AUDIT")
    print("=" * 100)

    print()
    print(
        "SNAPSHOT:",
        snapshot,
    )

    print()
    print(
        "SNAPSHOT TRADING LINES:",
        len(snapshot_ids),
    )

    print(
        "LIVE RAW TRADING LINES:",
        len(raw_ids),
    )

    print(
        "LIVE COMMON STOCK LINES:",
        len(common_ids),
    )

    print()
    print(
        "LIVE ADDED VS SNAPSHOT:",
        len(live_added_vs_snapshot),
    )

    print(
        "LIVE MISSING VS SNAPSHOT:",
        len(live_missing_vs_snapshot),
    )

    if live_added_vs_snapshot:
        print()
        print("LIVE ADDED VS SNAPSHOT")

        for line_id in live_added_vs_snapshot:
            record = row_description(raw_map[line_id])

            print(f"{line_id} | {record['company_name']} | {record['ticker']}")

    if live_missing_vs_snapshot:
        print()
        print("LIVE MISSING VS SNAPSHOT")

        snapshot_lookup = trading_lines.set_index("trading_line_id")

        for line_id in live_missing_vs_snapshot:
            row = snapshot_lookup.loc[line_id]

            print(f"{line_id} | {row['display_name']} | {row['ticker']}")

    if not exact_snapshot_match:
        result = {
            "snapshot": str(snapshot),
            "status": "FAIL_POINT_IN_TIME_BINDING",
            "snapshot_line_count": len(snapshot_ids),
            "live_raw_line_count": len(raw_ids),
            "live_added_vs_snapshot": live_added_vs_snapshot,
            "live_missing_vs_snapshot": live_missing_vs_snapshot,
        }

        OUTPUT.write_text(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print()
        print("=" * 100)
        print("STATUS: FAIL — LIVE DIRECTORY DOES NOT EXACTLY MATCH SNAPSHOT")
        print("=" * 100)

        print("No classification was bound to the frozen snapshot.")

        return

    # --------------------------------------------------------
    # BIND OFFICIAL CLASSIFICATION
    # --------------------------------------------------------

    classified = trading_lines.copy()

    classified["official_issue_type"] = "Common Stock"

    classified["official_issue_type_code"] = COMMON_STOCK_ISSUE_TYPE

    classified["is_common_stock"] = classified["trading_line_id"].isin(common_ids)

    # The textual issue-type label above only applies
    # positively. Avoid pretending we know the exact
    # alternative category of excluded instruments.
    classified.loc[
        ~classified["is_common_stock"],
        "official_issue_type",
    ] = None

    classified.loc[
        ~classified["is_common_stock"],
        "official_issue_type_code",
    ] = None

    # --------------------------------------------------------
    # SECURITY-LEVEL CONSISTENCY
    # --------------------------------------------------------

    security_summary = classified.groupby(
        "security_id",
        as_index=False,
    ).agg(
        trading_line_count=(
            "trading_line_id",
            "count",
        ),
        common_stock_line_count=(
            "is_common_stock",
            "sum",
        ),
    )

    security_summary["non_common_stock_line_count"] = (
        security_summary["trading_line_count"] - security_summary["common_stock_line_count"]
    )

    security_summary["classification"] = "mixed"

    all_common = (
        security_summary["common_stock_line_count"] == security_summary["trading_line_count"]
    )

    none_common = security_summary["common_stock_line_count"] == 0

    security_summary.loc[
        all_common,
        "classification",
    ] = "all_common_stock"

    security_summary.loc[
        none_common,
        "classification",
    ] = "no_common_stock_lines"

    mixed = security_summary[security_summary["classification"] == "mixed"]

    multi_line_ids = set(
        security_summary.loc[
            security_summary["trading_line_count"] > 1,
            "security_id",
        ]
    )

    multi_line_detail = classified[classified["security_id"].isin(multi_line_ids)][
        [
            "security_id",
            "trading_line_id",
            "display_name",
            "ticker",
            "reference_mic",
            "is_common_stock",
        ]
    ].sort_values(
        [
            "security_id",
            "reference_mic",
        ]
    )

    print()
    print("=" * 100)
    print("SECURITY CLASSIFICATION")
    print("=" * 100)

    print(
        "SECURITIES:",
        len(security_summary),
    )

    print(
        "ALL COMMON STOCK:",
        int((security_summary["classification"] == "all_common_stock").sum()),
    )

    print(
        "NO COMMON STOCK LINES:",
        int((security_summary["classification"] == "no_common_stock_lines").sum()),
    )

    print(
        "MIXED:",
        len(mixed),
    )

    print()
    print("=" * 100)
    print("MULTI-LINE SECURITY AUDIT")
    print("=" * 100)

    print(multi_line_detail.to_string(index=False))

    if not mixed.empty:
        print()
        print("=" * 100)
        print("MIXED SECURITY CLASSIFICATIONS")
        print("=" * 100)

        print(mixed.to_string(index=False))

    hard_gates = {
        "live_raw_exactly_matches_snapshot": exact_snapshot_match,
        "common_is_raw_subset": common_ids.issubset(raw_ids),
        "classification_exhaustive": len(classified) == len(snapshot_ids),
        "common_line_count_matches": int(classified["is_common_stock"].sum()) == len(common_ids),
        "no_mixed_security_classification": mixed.empty,
    }

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:45s}",
            ("PASS" if passed else "FAIL"),
        )

    failed = [name for name, passed in hard_gates.items() if not passed]

    result = {
        "snapshot": str(snapshot),
        "official_filter": {
            "label": "Common Stock",
            "field": "args[issueType]",
            "value": COMMON_STOCK_ISSUE_TYPE,
        },
        "counts": {
            "trading_lines": len(classified),
            "common_stock_lines": int(classified["is_common_stock"].sum()),
            "non_common_stock_lines": int((~classified["is_common_stock"]).sum()),
            "securities": len(security_summary),
            "mixed_securities": len(mixed),
        },
        "hard_gates": hard_gates,
    }

    OUTPUT.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "WROTE:",
        OUTPUT,
    )

    print()

    if failed:
        print("STATUS: FAIL")

        raise RuntimeError(f"Failed gates: {failed}")

    print("STATUS: PASS")


if __name__ == "__main__":
    main()
