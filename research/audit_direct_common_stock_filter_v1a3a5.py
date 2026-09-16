from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from euronext_pde.providers.euronext_universe import (
    COMPETITION_MICS,
    ENDPOINT,
    REFERER,
    build_payload,
    parse_name_fragment,
)

OUTPUT = Path("research") / "v1a3a5_direct_common_stock_filter_audit.json"

COMMON_STOCK_ISSUE_TYPE = "101"


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

    if not isinstance(result, dict):
        raise TypeError("Unexpected directory response.")

    return result


def rows(
    payload: dict[str, Any],
) -> list[list[Any]]:
    raw_rows = payload.get(
        "aaData",
        [],
    )

    if not isinstance(
        raw_rows,
        list,
    ):
        raise TypeError("aaData is not a list.")

    result: list[list[Any]] = []

    for row in raw_rows:
        if not isinstance(
            row,
            list,
        ):
            raise TypeError("Directory row is not a list.")

        result.append(row)

    return result


def row_record(
    row: list[Any],
) -> dict[str, str]:
    name, product_url = parse_name_fragment(str(row[0]))

    return {
        "company_name": name,
        "isin": str(row[1]).strip(),
        "ticker": str(row[2]).strip(),
        "product_url": product_url,
    }


def row_key(
    row: list[Any],
) -> tuple[str, str, str]:
    record = row_record(row)

    return (
        record["isin"],
        record["ticker"],
        record["product_url"],
    )


def main() -> None:
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
        raw = fetch_directory(
            client,
            common_stock_only=False,
        )

        common = fetch_directory(
            client,
            common_stock_only=True,
        )

    raw_rows = rows(raw)
    common_rows = rows(common)

    raw_total = int(raw["iTotalRecords"])

    common_total = int(common["iTotalRecords"])

    raw_map = {row_key(row): row for row in raw_rows}

    common_keys = {row_key(row) for row in common_rows}

    removed_keys = sorted(set(raw_map) - common_keys)

    removed = [row_record(raw_map[key]) for key in removed_keys]

    added_keys = sorted(common_keys - set(raw_map))

    print("=" * 100)
    print("V1A3A5 — DIRECT COMMON STOCK FILTER AUDIT")
    print("=" * 100)

    print()
    print(
        "MICS:",
        ",".join(COMPETITION_MICS),
    )

    print()
    print(
        "RAW TOTAL:",
        raw_total,
    )

    print(
        "RAW ROWS:",
        len(raw_rows),
    )

    print(
        "COMMON STOCK TOTAL:",
        common_total,
    )

    print(
        "COMMON STOCK ROWS:",
        len(common_rows),
    )

    print(
        "REMOVED:",
        len(removed),
    )

    print(
        "ADDED:",
        len(added_keys),
    )

    print()
    print("=" * 100)
    print("EXCLUDED BY OFFICIAL COMMON STOCK FILTER")
    print("=" * 100)

    for record in removed:
        print(f"{record['company_name']} | {record['isin']} | {record['ticker']}")

    hard_gates = {
        "raw_full_response": len(raw_rows) == raw_total,
        "common_full_response": len(common_rows) == common_total,
        "common_is_subset": not added_keys,
        "filter_removes_instruments": common_total < raw_total,
        "set_difference_matches": len(removed) == (raw_total - common_total),
    }

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:35s}",
            ("PASS" if passed else "FAIL"),
        )

    failed = [name for name, passed in hard_gates.items() if not passed]

    result = {
        "competition_mics": list(COMPETITION_MICS),
        "official_filter": {
            "field": "args[issueType]",
            "value": COMMON_STOCK_ISSUE_TYPE,
            "label": "Common Stock",
        },
        "raw_total": raw_total,
        "common_stock_total": common_total,
        "removed_count": len(removed),
        "removed": removed,
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
