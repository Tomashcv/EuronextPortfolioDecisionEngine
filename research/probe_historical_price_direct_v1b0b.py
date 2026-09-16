from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

TRADING_LINE_ID = "NL0000226223-XPAR"

PAGE_URL = f"https://live.euronext.com/en/popout-page/getHistoricalPrice/{TRADING_LINE_ID}"

AJAX_URL = f"https://live.euronext.com/en/ajax/getHistoricalPricePopup/{TRADING_LINE_ID}"

DOWNLOAD_URL = (
    f"https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/{TRADING_LINE_ID}"
)

OUTPUT = Path("research") / "v1b0b_historical_price_direct_probe.json"


def response_metadata(
    response: httpx.Response,
) -> dict[str, Any]:
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_disposition": response.headers.get("content-disposition"),
        "content_length_header": response.headers.get("content-length"),
        "body_bytes": len(response.content),
        "final_url": str(response.url),
    }


def print_metadata(
    label: str,
    response: httpx.Response,
) -> None:
    metadata = response_metadata(response)

    print()
    print("=" * 100)
    print(label)
    print("=" * 100)

    for key, value in metadata.items():
        print(
            f"{key:28s}",
            value,
        )


def json_summary(
    response: httpx.Response,
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {
            "is_json": False,
        }

    result: dict[
        str,
        Any,
    ] = {
        "is_json": True,
        "python_type": type(payload).__name__,
    }

    if isinstance(
        payload,
        dict,
    ):
        result["top_level_keys"] = list(payload.keys())

        values: dict[
            str,
            Any,
        ] = {}

        for key, value in payload.items():
            if isinstance(
                value,
                str,
            ):
                values[key] = {
                    "type": "str",
                    "length": len(value),
                    "preview": value[:1000],
                }

            elif isinstance(
                value,
                list,
            ):
                values[key] = {
                    "type": "list",
                    "length": len(value),
                    "preview": value[:3],
                }

            else:
                values[key] = {
                    "type": type(value).__name__,
                    "value": value,
                }

        result["values"] = values

    return result


def html_tables_from_json(
    response: httpx.Response,
) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        return []

    strings: list[tuple[str, str]] = []

    if isinstance(
        payload,
        dict,
    ):
        for key, value in payload.items():
            if isinstance(
                value,
                str,
            ):
                strings.append(
                    (
                        str(key),
                        value,
                    )
                )

    elif isinstance(
        payload,
        str,
    ):
        strings.append(
            (
                "root",
                payload,
            )
        )

    tables: list[dict[str, Any]] = []

    for key, value in strings:
        soup = BeautifulSoup(
            value,
            "html.parser",
        )

        for table in soup.find_all("table"):
            headers = [
                cell.get_text(
                    " ",
                    strip=True,
                )
                for cell in table.find_all("th")
            ]

            rows: list[list[str]] = []

            for row in table.find_all("tr"):
                cells = [
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                    for cell in row.find_all("td")
                ]

                if cells:
                    rows.append(cells)

            tables.append(
                {
                    "source_key": key,
                    "headers": headers,
                    "row_count": len(rows),
                    "first_rows": rows[:5],
                    "last_rows": rows[-5:],
                }
            )

    return tables


def ajax_request(
    client: httpx.Client,
    *,
    start_date: date,
    end_date: date,
    sessions: int,
    adjusted: str,
) -> httpx.Response:
    response = client.post(
        AJAX_URL,
        data={
            "format": "xls",
            "decimal_separator": ".",
            "date_form": "d/m/Y",
            "adjusted": adjusted,
            "startdate": start_date.isoformat(),
            "enddate": end_date.isoformat(),
            "nbSession": str(sessions),
        },
        headers={
            "Referer": PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    response.raise_for_status()

    return response


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

    result: dict[
        str,
        Any,
    ] = {
        "trading_line_id": TRADING_LINE_ID,
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        # ----------------------------------------------------
        # EXACT BROWSER REPRODUCTION
        # ----------------------------------------------------

        small = ajax_request(
            client,
            start_date=date(
                2026,
                9,
                1,
            ),
            end_date=date(
                2026,
                9,
                14,
            ),
            sessions=10,
            adjusted="Y",
        )

        print_metadata(
            "AJAX — EXACT BROWSER REPRODUCTION",
            small,
        )

        small_json = json_summary(small)

        small_tables = html_tables_from_json(small)

        print()
        print("JSON SUMMARY:")

        print(
            json.dumps(
                small_json,
                indent=2,
                ensure_ascii=False,
            )[:10000]
        )

        print()
        print("PARSED TABLES:")

        print(
            json.dumps(
                small_tables,
                indent=2,
                ensure_ascii=False,
            )
        )

        result["small_adjusted"] = {
            "metadata": response_metadata(small),
            "json": small_json,
            "tables": small_tables,
        }

        # ----------------------------------------------------
        # ONE-YEAR / LARGE SESSION PROBE
        # ----------------------------------------------------

        one_year = ajax_request(
            client,
            start_date=date(
                2025,
                9,
                14,
            ),
            end_date=date(
                2026,
                9,
                14,
            ),
            sessions=500,
            adjusted="Y",
        )

        print_metadata(
            "AJAX — 1 YEAR / 500 SESSIONS",
            one_year,
        )

        one_year_tables = html_tables_from_json(one_year)

        print()
        print("PARSED TABLES:")

        print(
            json.dumps(
                one_year_tables,
                indent=2,
                ensure_ascii=False,
            )
        )

        result["one_year_adjusted"] = {
            "metadata": response_metadata(one_year),
            "json": json_summary(one_year),
            "tables": one_year_tables,
        }

        # ----------------------------------------------------
        # SAME WINDOW, NON-ADJUSTED
        # ----------------------------------------------------

        one_year_raw = ajax_request(
            client,
            start_date=date(
                2025,
                9,
                14,
            ),
            end_date=date(
                2026,
                9,
                14,
            ),
            sessions=500,
            adjusted="N",
        )

        print_metadata(
            "AJAX — 1 YEAR / NON-ADJUSTED",
            one_year_raw,
        )

        raw_tables = html_tables_from_json(one_year_raw)

        result["one_year_non_adjusted"] = {
            "metadata": response_metadata(one_year_raw),
            "json": json_summary(one_year_raw),
            "tables": raw_tables,
        }

        # ----------------------------------------------------
        # FULL DOWNLOAD
        # ----------------------------------------------------

        download = client.get(
            DOWNLOAD_URL,
            params={
                "format": "csv",
                "decimal_separator": ".",
                "date_form": "d/m/Y",
            },
            headers={
                "Referer": PAGE_URL,
            },
        )

        download.raise_for_status()

        print_metadata(
            "FULL DOWNLOAD — CSV",
            download,
        )

        content_type = download.headers.get("content-type", "")

        text_preview: str | None = None

        if (
            "text" in content_type.lower()
            or "json" in content_type.lower()
            or "csv" in content_type.lower()
        ):
            text_preview = download.text[:5000]

            print()
            print("DOWNLOAD PREVIEW:")

            print(text_preview)

        else:
            print()
            print("DOWNLOAD FIRST 64 BYTES:")

            print(download.content[:64])

        result["full_download_csv"] = {
            "metadata": response_metadata(download),
            "text_preview": text_preview,
            "first_64_bytes_hex": download.content[:64].hex(),
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
    print(
        "WROTE:",
        OUTPUT,
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
