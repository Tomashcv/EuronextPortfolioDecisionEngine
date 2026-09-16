from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://live.euronext.com"

REFERER = f"{BASE}/en/products/equities/regulated/list"

ENDPOINT = f"{BASE}/en/product_directory/data/stocks-euronext-regulated"

MICS = [
    "MTAA",  # Milan
    "XAMS",  # Amsterdam
    "XBRU",  # Brussels
    "XLIS",  # Lisbon
    "XMSM",  # Dublin
    "XOSL",  # Oslo
    "XPAR",  # Paris
]

DISPLAY_POINTS = "name,isin,symbol,market,lastPrice,precentDayChange,lastTradeTime"


def build_payload(length: int = 20) -> dict[str, str]:
    payload: dict[str, str] = {
        "draw": "1",
        "start": "0",
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "0",
        "order[0][dir]": "asc",
        "args[display_datapoints]": DISPLAY_POINTS,
        "iDisplayLength": str(length),
        "iDisplayStart": "0",
        "sSortDir_0": "asc",
        "sSortField": "shortName",
    }

    for i in range(7):
        payload[f"columns[{i}][data]"] = str(i)
        payload[f"columns[{i}][name]"] = ""
        payload[f"columns[{i}][searchable]"] = "true"
        payload[f"columns[{i}][orderable]"] = "true" if i == 0 else "false"
        payload[f"columns[{i}][search][value]"] = ""
        payload[f"columns[{i}][search][regex]"] = "false"

    return payload


def main() -> None:
    output_dir = Path("data") / "raw" / "euronext"

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = output_dir / f"universe_api_probe_{datetime.now(UTC).date().isoformat()}.json"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": REFERER,
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        # Establish normal site cookies/session first.
        landing = client.get(REFERER)

        print(
            "LANDING:",
            landing.status_code,
        )

        response = client.post(
            ENDPOINT,
            params={
                "mics": ",".join(MICS),
            },
            data=build_payload(length=2000),
        )

    print(
        "API HTTP:",
        response.status_code,
    )

    print(
        "CONTENT TYPE:",
        response.headers.get("content-type"),
    )

    response.raise_for_status()

    try:
        payload = response.json()

    except json.JSONDecodeError:
        print()
        print("NON-JSON RESPONSE:")
        print(response.text[:5000])
        raise

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 100)
    print("V1A1 — DIRECT EURONEXT UNIVERSE API PROBE")
    print("=" * 100)

    if isinstance(payload, dict):
        print()
        print(
            "TOP-LEVEL KEYS:",
            list(payload.keys()),
        )

        for key in (
            "draw",
            "recordsTotal",
            "recordsFiltered",
            "iTotalRecords",
            "iTotalDisplayRecords",
        ):
            if key in payload:
                print(
                    f"{key}:",
                    payload[key],
                )

        data = payload.get(
            "data",
            payload.get(
                "aaData",
                [],
            ),
        )

    else:
        data = payload

    print()
    print(
        "DATA TYPE:",
        type(data).__name__,
    )

    try:
        print(
            "ROWS RETURNED:",
            len(data),
        )
    except TypeError:
        pass

    print()
    print("=" * 100)
    print("FIRST ROWS")
    print("=" * 100)

    if isinstance(data, list):
        for i, row in enumerate(
            data[:10],
            start=1,
        ):
            print()
            print(f"ROW {i}:")
            print(
                json.dumps(
                    row,
                    indent=2,
                    ensure_ascii=False,
                )
            )

    else:
        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
        )

    print()
    print(
        "RAW SNAPSHOT:",
        output_path,
    )


if __name__ == "__main__":
    main()
