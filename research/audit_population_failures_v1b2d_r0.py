from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

OUTPUT = Path("research") / "v1b2d_r0_failure_raw_audit.json"

BORSA_BASE = "https://grafici.borsaitaliana.it/api/instruments"

EURONEXT_BASE = "https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax"

TOKEN_PATTERN = re.compile(r'token="([^"]+)"')

BORSA_FIELDS = (
    "dt",
    "openPx",
    "highPx",
    "lowPx",
    "lastPx",
    "closePx",
    "qty",
    "volNbTrade",
    "volCap",
    "vwap",
)

MTAA_CASES = (
    (
        "IT0005481855",
        "MET.EXTRA GROUP",
    ),
    (
        "IT0005730095",
        "EPH INVEST",
    ),
)

HAL_ISIN = "BMG455841020"
HAL_LINE = "BMG455841020-XAMS"


def get_borsa_token(
    client: httpx.Client,
    isin: str,
) -> tuple[
    str,
    str,
]:
    chart_url = f"https://grafici.borsaitaliana.it/interactive-chart/{isin}-XMIL?lang=it"

    response = client.get(
        chart_url,
        timeout=30.0,
    )

    response.raise_for_status()

    match = TOKEN_PATTERN.search(response.text)

    if match is None:
        raise RuntimeError(f"JWT not found for {isin}.")

    return (
        match.group(1),
        chart_url,
    )


def audit_borsa(
    client: httpx.Client,
    *,
    isin: str,
    name: str,
) -> dict[str, Any]:
    token, chart_url = get_borsa_token(
        client,
        isin,
    )

    response = client.get(
        (f"{BORSA_BASE}/{isin},XMIL,ISIN/history/period"),
        params={
            "period": "5Y",
            "adjustment": "true",
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

    history = payload.get("history")

    if not isinstance(
        history,
        dict,
    ):
        raise TypeError("Missing history object.")

    rows = history.get("historyDt")

    if not isinstance(
        rows,
        list,
    ):
        raise TypeError("Missing historyDt.")

    field_missing: Counter[str] = Counter()

    incomplete_rows: list[dict[str, Any]] = []

    row_count = len(rows)

    for index, row in enumerate(rows):
        if not isinstance(
            row,
            dict,
        ):
            raise TypeError("Non-dict history row.")

        missing = [
            field
            for field in BORSA_FIELDS
            if (field not in row or row.get(field) is None or str(row.get(field)).strip() == "")
        ]

        for field in missing:
            field_missing[field] += 1

        if missing:
            sessions_from_end = row_count - 1 - index

            incomplete_rows.append(
                {
                    "index": index,
                    "sessions_from_end": sessions_from_end,
                    "dt": row.get("dt"),
                    "missing": missing,
                    "closePx": row.get("closePx"),
                    "openPx": row.get("openPx"),
                    "highPx": row.get("highPx"),
                    "lowPx": row.get("lowPx"),
                    "lastPx": row.get("lastPx"),
                    "qty": row.get("qty"),
                    "volNbTrade": row.get("volNbTrade"),
                    "volCap": row.get("volCap"),
                    "vwap": row.get("vwap"),
                }
            )

    close_missing = int(field_missing["closePx"])

    incomplete_last_20 = sum(item["sessions_from_end"] < 20 for item in incomplete_rows)

    incomplete_last_61 = sum(item["sessions_from_end"] < 61 for item in incomplete_rows)

    incomplete_last_127 = sum(item["sessions_from_end"] < 127 for item in incomplete_rows)

    incomplete_last_252 = sum(item["sessions_from_end"] < 252 for item in incomplete_rows)

    return {
        "name": name,
        "isin": isin,
        "status": response.status_code,
        "provider_mic": (
            payload.get(
                "transco",
                {},
            ).get("exchCode")
        ),
        "rows": row_count,
        "first_date": (
            rows[0].get("dt")
            if rows
            and isinstance(
                rows[0],
                dict,
            )
            else None
        ),
        "last_date": (
            rows[-1].get("dt")
            if rows
            and isinstance(
                rows[-1],
                dict,
            )
            else None
        ),
        "missing_by_field": dict(sorted(field_missing.items())),
        "incomplete_row_count": len(incomplete_rows),
        "close_missing_count": close_missing,
        "all_incomplete_rows_have_close": (bool(incomplete_rows) and close_missing == 0),
        "incomplete_rows_last_20": incomplete_last_20,
        "incomplete_rows_last_61": incomplete_last_61,
        "incomplete_rows_last_127": incomplete_last_127,
        "incomplete_rows_last_252": incomplete_last_252,
        "incomplete_rows": incomplete_rows,
    }


def audit_hal(
    client: httpx.Client,
) -> dict[str, Any]:
    response = client.get(
        (f"{EURONEXT_BASE}/{HAL_LINE}"),
        params={
            "format": "csv",
            "decimal_separator": ".",
            "date_form": "d/m/Y",
        },
        headers={
            "Referer": (f"https://live.euronext.com/en/popout-page/getHistoricalPrice/{HAL_LINE}"),
        },
        timeout=30.0,
    )

    response.raise_for_status()

    raw_lines = response.text.splitlines()

    nonempty_lines = [line for line in raw_lines if line.strip()]

    parsed_rows: list[dict[str, str]] = []

    header_index: int | None = None

    for index, line in enumerate(nonempty_lines):
        if "Date;" in line and "Close" in line:
            header_index = index

            break

    if header_index is not None:
        reader = csv.DictReader(
            io.StringIO("\n".join(nonempty_lines[header_index:])),
            delimiter=";",
        )

        parsed_rows = list(reader)

    return {
        "name": "HAL TRUST",
        "isin": HAL_ISIN,
        "trading_line_id": HAL_LINE,
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_disposition": response.headers.get("content-disposition"),
        "body_bytes": len(response.content),
        "raw_line_count": len(raw_lines),
        "nonempty_line_count": len(nonempty_lines),
        "header_index": header_index,
        "parsed_row_count": len(parsed_rows),
        "first_15_nonempty_lines": nonempty_lines[:15],
        "last_10_nonempty_lines": nonempty_lines[-10:],
        "first_parsed_row": (parsed_rows[0] if parsed_rows else None),
        "last_parsed_row": (parsed_rows[-1] if parsed_rows else None),
    }


def main() -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    artifact: dict[
        str,
        Any,
    ] = {
        "milestone": "V1B2D-R0",
        "purpose": ("Read-only raw inspection of the three deterministic population failures."),
        "secrets_persisted": False,
        "borsa_cases": [],
        "euronext_cases": [],
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        for isin, name in MTAA_CASES:
            result = audit_borsa(
                client,
                isin=isin,
                name=name,
            )

            artifact["borsa_cases"].append(result)

            print()
            print("=" * 100)
            print(
                name,
                isin,
            )
            print("=" * 100)

            print(
                "STATUS:",
                result["status"],
            )

            print(
                "ROWS:",
                result["rows"],
            )

            print(
                "RANGE:",
                result["first_date"],
                "->",
                result["last_date"],
            )

            print(
                "MISSING BY FIELD:",
                result["missing_by_field"],
            )

            print(
                "INCOMPLETE ROWS:",
                result["incomplete_row_count"],
            )

            print(
                "CLOSE MISSING:",
                result["close_missing_count"],
            )

            print(
                "INCOMPLETE LAST 20:",
                result["incomplete_rows_last_20"],
            )

            print(
                "INCOMPLETE LAST 61:",
                result["incomplete_rows_last_61"],
            )

            print(
                "INCOMPLETE LAST 127:",
                result["incomplete_rows_last_127"],
            )

            print(
                "INCOMPLETE LAST 252:",
                result["incomplete_rows_last_252"],
            )

            print()
            print("INCOMPLETE ROW DETAILS")

            for item in result["incomplete_rows"]:
                print(
                    json.dumps(
                        item,
                        ensure_ascii=False,
                    )
                )

        hal = audit_hal(client)

        artifact["euronext_cases"].append(hal)

        print()
        print("=" * 100)
        print(
            "HAL TRUST",
            HAL_LINE,
        )
        print("=" * 100)

        print(
            "STATUS:",
            hal["status"],
        )

        print(
            "CONTENT TYPE:",
            hal["content_type"],
        )

        print(
            "BODY BYTES:",
            hal["body_bytes"],
        )

        print(
            "NONEMPTY LINES:",
            hal["nonempty_line_count"],
        )

        print(
            "HEADER INDEX:",
            hal["header_index"],
        )

        print(
            "PARSED ROWS:",
            hal["parsed_row_count"],
        )

        print()
        print("FIRST 15 NONEMPTY LINES")

        for line in hal["first_15_nonempty_lines"]:
            print(repr(line))

    OUTPUT.write_text(
        json.dumps(
            artifact,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 100)
    print(
        "WROTE:",
        OUTPUT,
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
