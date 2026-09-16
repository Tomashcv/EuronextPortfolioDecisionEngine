from __future__ import annotations

import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

URL = "https://live.euronext.com/en/products/equities/regulated/list"

OUTPUT = Path("research") / "v1a0_euronext_network_discovery.json"


def main() -> None:
    options = Options()

    options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    options.set_capability(
        "goog:loggingPrefs",
        {"performance": "ALL"},
    )

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(URL)

        # Allow dynamic tables / XHR calls to load.
        time.sleep(10)

        # Force lazy-loaded content to initialize.
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        time.sleep(5)

        logs = driver.get_log("performance")

    finally:
        driver.quit()

    records: list[dict[str, object]] = []

    keywords = (
        "euronext",
        "equities",
        "instrument",
        "filter",
        "/pd/",
        "/ajax/",
        "market",
    )

    for item in logs:
        try:
            payload = json.loads(item["message"])["message"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue

        method_name = payload.get("method")

        if method_name != "Network.requestWillBeSent":
            continue

        params = payload.get("params", {})
        request = params.get("request", {})

        url = str(request.get("url", ""))

        lower = url.lower()

        if not any(keyword in lower for keyword in keywords):
            continue

        record = {
            "method": request.get("method"),
            "url": url,
            "resource_type": params.get("type"),
            "post_data": request.get("postData"),
        }

        records.append(record)

    # Deduplicate while preserving useful POST bodies.
    unique: list[dict[str, object]] = []
    seen: set[tuple[object, object, object]] = set()

    for record in records:
        key = (
            record["method"],
            record["url"],
            record["post_data"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(record)

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT.write_text(
        json.dumps(
            unique,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 100)
    print("V1A0 — EURONEXT LIVE NETWORK DISCOVERY")
    print("=" * 100)

    print()
    print("PAGE:")
    print(URL)

    print()
    print("CANDIDATE REQUESTS:", len(unique))

    for index, record in enumerate(unique, start=1):
        print()
        print("-" * 100)
        print(f"[{index}] {record['method']} {record['url']}")

        if record["post_data"]:
            print("POST DATA:")
            print(record["post_data"])

    print()
    print("=" * 100)
    print("WROTE:", OUTPUT)
    print("=" * 100)


if __name__ == "__main__":
    main()
