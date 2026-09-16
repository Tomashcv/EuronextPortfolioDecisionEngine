from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

URL = "https://live.euronext.com/en/products/equities/regulated/list"

TABLE_FRAGMENT = "/en/product_directory/data/stocks-euronext-regulated"

OUTPUT = Path("research") / "v1a3a2_common_stock_form_post.json"


def relevant_post_requests(
    logs: list[dict[str, object]],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for item in logs:
        try:
            message = json.loads(str(item["message"]))["message"]
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

        if request.get("method") != "POST":
            continue

        request_url = str(request.get("url", ""))

        if request_url != URL and TABLE_FRAGMENT not in request_url:
            continue

        records.append(
            {
                "url": request_url,
                "method": request.get("method"),
                "post_data": request.get("postData"),
            }
        )

    return records


def decoded_post_data(
    post_data: object,
) -> list[tuple[str, str]]:
    if not isinstance(post_data, str):
        return []

    return parse_qsl(
        post_data,
        keep_blank_values=True,
    )


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

    requests: list[dict[str, object]] = []

    form_entries: list[list[str]] = []

    try:
        driver.get(URL)

        time.sleep(8)

        label = driver.find_element(
            By.XPATH,
            ("//label[normalize-space()='Common Stock']"),
        )

        input_id = label.get_attribute("for")

        if not input_id:
            raise RuntimeError("Common Stock label has no input ID.")

        checkbox = driver.find_element(
            By.ID,
            input_id,
        )

        driver.execute_script(
            "arguments[0].click();",
            checkbox,
        )

        if not checkbox.is_selected():
            raise RuntimeError("Common Stock checkbox is not selected.")

        form = driver.find_element(
            By.ID,
            "awl-pd-filter-es-form",
        )

        # Capture exactly what a normal browser form submission
        # is about to send.
        raw_entries = driver.execute_script(
            """
            const data = new FormData(arguments[0]);
            return Array.from(
                data.entries()
            ).map(([key, value]) => [
                String(key),
                String(value)
            ]);
            """,
            form,
        )

        if not isinstance(
            raw_entries,
            list,
        ):
            raise TypeError("Unexpected FormData result.")

        form_entries = raw_entries

        print("=" * 100)
        print("V1A3A2 â€” COMMON STOCK FORM SERIALIZATION")
        print("=" * 100)

        print()
        print("RELEVANT FORM FIELDS")

        relevant_prefixes = (
            "issueType",
            "form_",
            "op",
        )

        for key, value in form_entries:
            if key.startswith(relevant_prefixes):
                print(f"{key} = {value}")

        # Throw away all previous network traffic.
        driver.get_log("performance")

        submit = driver.find_element(
            By.ID,
            "edit-awl-pd-filters-es-submit",
        )

        driver.execute_script(
            "arguments[0].click();",
            submit,
        )

        time.sleep(10)

        requests = relevant_post_requests(driver.get_log("performance"))

    finally:
        driver.quit()

    print()
    print("=" * 100)
    print("POST REQUESTS AFTER SUBMIT")
    print("=" * 100)

    for index, request in enumerate(
        requests,
        start=1,
    ):
        print()
        print(f"REQUEST {index}")

        print(
            request["method"],
            request["url"],
        )

        decoded = decoded_post_data(request["post_data"])

        print()
        print("RELEVANT DECODED FIELDS")

        found = False

        for key, value in decoded:
            if key.startswith(("issueType", "form_")) or key == "op":
                print(f"{key} = {value}")
                found = True

        if not found:
            print("NONE")

        print()
        print(
            "RAW POST LENGTH:",
            (
                len(request["post_data"])
                if isinstance(
                    request["post_data"],
                    str,
                )
                else 0
            ),
        )

    result = {
        "page": URL,
        "serialized_form_entries": form_entries,
        "post_requests": requests,
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
    print("WROTE:", OUTPUT)
    print("=" * 100)


if __name__ == "__main__":
    main()
