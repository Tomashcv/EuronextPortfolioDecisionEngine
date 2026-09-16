from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PAGES = {
    "regulated": ("https://live.euronext.com/en/products/equities/regulated/list"),
    "growth": ("https://live.euronext.com/en/products/equities/growth/list"),
    "access": ("https://live.euronext.com/en/products/equities/access/list"),
    "expand": ("https://live.euronext.com/en/products/equities/expand/list"),
    "global_equity_market": (
        "https://live.euronext.com/en/products/equities/global-equity-market/list"
    ),
    "all_equities": ("https://live.euronext.com/en/products/equities/list"),
}

TARGET_FRAGMENT = "/product_directory/data/"

OUTPUT = Path("research") / "v1a4a_equity_market_family_endpoints.json"


def extract_requests(
    logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in logs:
        try:
            message = json.loads(item["message"])["message"]
        except (
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ):
            continue

        if message.get("method") != "Network.requestWillBeSent":
            continue

        try:
            request = message["params"]["request"]
        except (
            KeyError,
            TypeError,
        ):
            continue

        url = str(request.get("url", ""))

        if TARGET_FRAGMENT not in url:
            continue

        records.append(
            {
                "method": request.get("method"),
                "url": url,
                "post_data": request.get("postData"),
            }
        )

    return records


def main() -> None:
    options = Options()

    options.add_argument("--headless=new")

    options.add_argument("--window-size=1600,1400")

    options.add_argument("--disable-gpu")

    options.set_capability(
        "goog:loggingPrefs",
        {
            "performance": "ALL",
        },
    )

    driver = webdriver.Chrome(options=options)

    result: dict[str, Any] = {}

    try:
        for family, page_url in PAGES.items():
            print()
            print("=" * 100)
            print(family.upper())
            print("=" * 100)

            # Remove prior network events.
            driver.get_log("performance")

            driver.get(page_url)

            time.sleep(7)

            records = extract_requests(driver.get_log("performance"))

            print(
                "PAGE:",
                page_url,
            )

            print(
                "DIRECTORY REQUESTS:",
                len(records),
            )

            for record in records:
                print()
                print(
                    record["method"],
                    record["url"],
                )

                post_data = record.get("post_data")

                if isinstance(
                    post_data,
                    str,
                ):
                    print(
                        "POST LENGTH:",
                        len(post_data),
                    )

            result[family] = {
                "page_url": page_url,
                "requests": records,
            }

    finally:
        driver.quit()

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
