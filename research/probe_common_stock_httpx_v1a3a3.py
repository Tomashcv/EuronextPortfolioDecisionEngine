from __future__ import annotations

from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from euronext_pde.providers.euronext_universe import (
    COMPETITION_MICS,
    ENDPOINT,
    REFERER,
    build_payload,
    parse_name_fragment,
)

PAGE_URL = REFERER

COMMON_STOCK_FIELD = "issueType[101][101]"
COMMON_STOCK_VALUE = "101"


def fetch_table(
    client: httpx.Client,
) -> dict[str, object]:

    response = client.post(
        ENDPOINT,
        params={
            "mics": ",".join(COMPETITION_MICS),
        },
        data=build_payload(
            start=0,
            length=2000,
            draw=1,
        ),
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise TypeError("Unexpected table response.")

    return payload


def row_key(
    row: list[object],
) -> tuple[str, str, str]:

    _, product_url = parse_name_fragment(str(row[0]))

    return (
        str(row[1]).strip(),
        str(row[2]).strip(),
        product_url,
    )


def row_label(
    row: list[object],
) -> str:

    name, _ = parse_name_fragment(str(row[0]))

    return f"{name} | {row[1]} | {row[2]}"


def main() -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        # ====================================================
        # GET PAGE / ESTABLISH SESSION
        # ====================================================

        landing = client.get(PAGE_URL)

        landing.raise_for_status()

        print("=" * 100)
        print("V1A3A3 — DIRECT COMMON STOCK SESSION FILTER")
        print("=" * 100)

        print()
        print(
            "LANDING:",
            landing.status_code,
        )

        print(
            "COOKIES AFTER GET:",
            len(client.cookies),
        )

        # ====================================================
        # RAW TABLE BEFORE FILTER
        # ====================================================

        raw_payload = fetch_table(client)

        raw_total = int(raw_payload["iTotalRecords"])

        raw_rows = raw_payload.get(
            "aaData",
            [],
        )

        if not isinstance(
            raw_rows,
            list,
        ):
            raise TypeError("Raw aaData is not a list.")

        print()
        print(
            "RAW TOTAL:",
            raw_total,
        )

        print(
            "RAW ROWS RETURNED:",
            len(raw_rows),
        )

        # ====================================================
        # PARSE FILTER FORM
        # ====================================================

        soup = BeautifulSoup(
            landing.text,
            "html.parser",
        )

        form = soup.select_one("#awl-pd-filter-es-form")

        if form is None:
            raise RuntimeError("Filter form not found.")

        action = form.get("action")

        form_url = urljoin(
            PAGE_URL,
            str(action or PAGE_URL),
        )

        form_data: list[tuple[str, str]] = []

        for node in form.select("input[type='hidden']"):
            name = node.get("name")

            if not name:
                continue

            value = node.get(
                "value",
                "",
            )

            form_data.append(
                (
                    str(name),
                    str(value),
                )
            )

        form_data.append(
            (
                COMMON_STOCK_FIELD,
                COMMON_STOCK_VALUE,
            )
        )

        form_data.append(
            (
                "op",
                "Submit",
            )
        )

        print()
        print("FILTER FORM:")

        for key, value in form_data:
            if (
                key.startswith(
                    (
                        "issueType",
                        "form_",
                    )
                )
                or key == "op"
            ):
                print(f"  {key} = {value}")

        # ====================================================
        # SUBMIT FILTER FORM IN SAME SESSION
        # ====================================================

        encoded_form = urlencode(form_data)

        submit = client.post(
            form_url,
            content=encoded_form.encode("utf-8"),
            headers={
                "Referer": PAGE_URL,
                "Content-Type": ("application/x-www-form-urlencoded"),
            },
        )

        submit.raise_for_status()

        print()
        print(
            "FORM POST:",
            submit.status_code,
        )

        print(
            "FINAL FORM URL:",
            submit.url,
        )

        print(
            "COOKIES AFTER POST:",
            len(client.cookies),
        )

        print(
            "REDIRECT COUNT:",
            len(submit.history),
        )

        for index, response in enumerate(
            submit.history,
            start=1,
        ):
            print(
                f"REDIRECT {index}:",
                response.status_code,
                response.url,
            )

            if response.headers.get("set-cookie"):
                print(
                    "  SET-COOKIE:",
                    response.headers["set-cookie"],
                )

        # Verify server-rendered form state if possible.
        submitted_soup = BeautifulSoup(
            submit.text,
            "html.parser",
        )

        common_stock = submitted_soup.select_one("#edit-issuetype-101-101")

        if common_stock is None:
            print("COMMON STOCK CONTROL AFTER POST: NOT FOUND")
        else:
            print(
                "COMMON STOCK CHECKED AFTER POST:",
                common_stock.has_attr("checked"),
            )

        # ====================================================
        # TABLE AFTER FILTER
        # ====================================================

        filtered_payload = fetch_table(client)

        filtered_total = int(filtered_payload["iTotalRecords"])

        filtered_rows = filtered_payload.get(
            "aaData",
            [],
        )

        if not isinstance(
            filtered_rows,
            list,
        ):
            raise TypeError("Filtered aaData is not a list.")

        print()
        print(
            "FILTERED TOTAL:",
            filtered_total,
        )

        print(
            "FILTERED ROWS RETURNED:",
            len(filtered_rows),
        )

        print(
            "REMOVED:",
            raw_total - filtered_total,
        )

        # ====================================================
        # SET DIFFERENCE AUDIT
        # ====================================================

        raw_map = {row_key(row): row for row in raw_rows if isinstance(row, list)}

        filtered_keys = {row_key(row) for row in filtered_rows if isinstance(row, list)}

        removed_keys = set(raw_map) - filtered_keys

        print()
        print(
            "SET-DIFFERENCE REMOVED:",
            len(removed_keys),
        )

        print()
        print("=" * 100)
        print("FIRST 40 REMOVED INSTRUMENTS")
        print("=" * 100)

        for key in sorted(removed_keys)[:40]:
            row = raw_map[key]

            print(row_label(row))

        print()
        print("=" * 100)

        if filtered_total >= raw_total:
            print("STATUS: FILTER NOT CONFIRMED")
        elif len(filtered_rows) != filtered_total:
            print("STATUS: FILTERED BUT FULL DATA NOT RETURNED")
        elif len(removed_keys) != (raw_total - filtered_total):
            print("STATUS: FILTERED BUT SET DIFFERENCE MISMATCH")
        else:
            print("STATUS: COMMON STOCK FILTER CONFIRMED")


if __name__ == "__main__":
    main()
