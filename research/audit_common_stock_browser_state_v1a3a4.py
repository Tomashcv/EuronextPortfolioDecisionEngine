from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

URL = "https://live.euronext.com/en/products/equities/regulated/list"

TARGET_FRAGMENT = "/en/product_directory/data/stocks-euronext-regulated"

OUTPUT = Path("research") / "v1a3a4_browser_filter_state_audit.json"


def parse_performance_logs(
    driver: webdriver.Chrome,
    logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    responses: dict[str, dict[str, Any]] = {}

    for item in logs:
        try:
            message = json.loads(item["message"])["message"]
        except (
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ):
            continue

        method = message.get("method")

        if method == "Network.requestWillBeSent":
            params = message.get("params", {})
            request = params.get("request", {})

            url = str(request.get("url", ""))

            if TARGET_FRAGMENT not in url:
                continue

            request_id = str(params.get("requestId"))

            requests[request_id] = {
                "request_id": request_id,
                "method": request.get("method"),
                "url": url,
                "headers": request.get(
                    "headers",
                    {},
                ),
                "post_data": request.get("postData"),
            }

        elif method == "Network.responseReceived":
            params = message.get("params", {})
            response = params.get("response", {})

            url = str(response.get("url", ""))

            if TARGET_FRAGMENT not in url:
                continue

            request_id = str(params.get("requestId"))

            responses[request_id] = {
                "status": response.get("status"),
                "headers": response.get(
                    "headers",
                    {},
                ),
            }

    records: list[dict[str, Any]] = []

    for request_id, request in requests.items():
        response = responses.get(
            request_id,
            {},
        )

        body_text: str | None = None
        body_json: dict[str, Any] | None = None

        try:
            body_result = driver.execute_cdp_cmd(
                "Network.getResponseBody",
                {
                    "requestId": request_id,
                },
            )

            body_text = body_result.get("body")

            if body_text:
                parsed = json.loads(body_text)

                if isinstance(
                    parsed,
                    dict,
                ):
                    body_json = parsed

        except (
            json.JSONDecodeError,
            WebDriverException,
        ):
            pass

        records.append(
            {
                **request,
                "response": response,
                "response_json": body_json,
                "response_body_length": (len(body_text) if body_text else None),
            }
        )

    return records


def storage_snapshot(
    driver: webdriver.Chrome,
) -> dict[str, Any]:
    result = driver.execute_script(
        """
        return {
            localStorage: Object.fromEntries(
                Object.entries(localStorage)
            ),
            sessionStorage: Object.fromEntries(
                Object.entries(sessionStorage)
            )
        };
        """
    )

    if not isinstance(
        result,
        dict,
    ):
        raise TypeError("Unexpected browser storage result.")

    return result


def table_info(
    driver: webdriver.Chrome,
) -> list[str]:
    selectors = (
        ".dataTables_info",
        "[id$='_info']",
    )

    values: list[str] = []

    for selector in selectors:
        nodes = driver.find_elements(
            By.CSS_SELECTOR,
            selector,
        )

        for node in nodes:
            text = node.text.strip()

            if text and text not in values:
                values.append(text)

    return values


def summarize_requests(
    label: str,
    records: list[dict[str, Any]],
) -> None:
    print()
    print("=" * 100)
    print(label)
    print("=" * 100)

    print(
        "TARGET REQUESTS:",
        len(records),
    )

    for index, record in enumerate(
        records,
        start=1,
    ):
        print()
        print(f"REQUEST {index}")

        print(
            record["method"],
            record["url"],
        )

        print()
        print("REQUEST HEADERS")

        headers = record.get(
            "headers",
            {},
        )

        interesting_headers = {
            key: value
            for key, value in headers.items()
            if (
                key.lower().startswith("x-")
                or key.lower()
                in {
                    "cookie",
                    "referer",
                    "origin",
                    "content-type",
                }
            )
        }

        print(
            json.dumps(
                interesting_headers,
                indent=2,
                ensure_ascii=False,
            )
        )

        print()
        print("POST DATA:")

        print(record.get("post_data"))

        response_json = record.get("response_json")

        if isinstance(
            response_json,
            dict,
        ):
            print()
            print(
                "RESPONSE TOTAL:",
                response_json.get("iTotalRecords"),
            )

            print(
                "RESPONSE DISPLAY TOTAL:",
                response_json.get("iTotalDisplayRecords"),
            )

            rows = response_json.get("aaData")

            print(
                "RESPONSE ROWS:",
                (
                    len(rows)
                    if isinstance(
                        rows,
                        list,
                    )
                    else None
                ),
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

    baseline_records: list[dict[str, Any]] = []

    filtered_records: list[dict[str, Any]] = []

    try:
        driver.execute_cdp_cmd(
            "Network.enable",
            {},
        )

        driver.get(URL)

        time.sleep(8)

        baseline_logs = driver.get_log("performance")

        baseline_records = parse_performance_logs(
            driver,
            baseline_logs,
        )

        print("=" * 100)
        print("V1A3A4 — BROWSER FILTER STATE AUDIT")
        print("=" * 100)

        summarize_requests(
            "BASELINE NETWORK",
            baseline_records,
        )

        print()
        print(
            "BASELINE TABLE INFO:",
            table_info(driver),
        )

        print(
            "BASELINE COOKIES:",
            driver.get_cookies(),
        )

        print("BASELINE STORAGE:")

        print(
            json.dumps(
                storage_snapshot(driver),
                indent=2,
                ensure_ascii=False,
            )
        )

        # ----------------------------------------------------
        # APPLY COMMON STOCK
        # ----------------------------------------------------

        label = driver.find_element(
            By.XPATH,
            ("//label[normalize-space()='Common Stock']"),
        )

        input_id = label.get_attribute("for")

        if not input_id:
            raise RuntimeError("Common Stock input ID missing.")

        checkbox = driver.find_element(
            By.ID,
            input_id,
        )

        driver.execute_script(
            """
            arguments[0].scrollIntoView({
                block: 'center'
            });
            """,
            label,
        )

        time.sleep(1)

        # The Euronext UI uses a hidden custom checkbox.
        # The associated label is the actual interactive control.
        driver.execute_script(
            "arguments[0].click();",
            checkbox,
        )

        time.sleep(1)

        print()
        print(
            "CHECKED AFTER CLICK:",
            checkbox.is_selected(),
        )

        # Drop events generated by checkbox selection itself.
        driver.get_log("performance")

        submit = driver.find_element(
            By.ID,
            "edit-awl-pd-filters-es-submit",
        )

        driver.execute_script(
            """
            arguments[0].scrollIntoView({
                block: 'center'
            });
            """,
            submit,
        )

        time.sleep(1)

        # Use an actual Selenium click, not form.submit()
        # or requestSubmit(), so the site's click handlers run.
        driver.execute_script(
            "arguments[0].click();",
            submit,
        )

        time.sleep(10)

        filtered_logs = driver.get_log("performance")

        filtered_records = parse_performance_logs(
            driver,
            filtered_logs,
        )

        print()
        print(
            "CURRENT URL:",
            driver.current_url,
        )

        common_after = driver.find_elements(
            By.ID,
            input_id,
        )

        if common_after:
            print(
                "CHECKED AFTER SUBMIT:",
                common_after[0].is_selected(),
            )
        else:
            print("CHECKED AFTER SUBMIT: CONTROL NOT FOUND")

        print(
            "FILTERED TABLE INFO:",
            table_info(driver),
        )

        print(
            "FILTERED COOKIES:",
            driver.get_cookies(),
        )

        print("FILTERED STORAGE:")

        print(
            json.dumps(
                storage_snapshot(driver),
                indent=2,
                ensure_ascii=False,
            )
        )

        summarize_requests(
            "FILTERED NETWORK",
            filtered_records,
        )

    finally:
        driver.quit()

    result = {
        "baseline_requests": baseline_records,
        "filtered_requests": filtered_records,
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
    from selenium.common.exceptions import (
        WebDriverException,
    )

    main()
