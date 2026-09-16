from __future__ import annotations

import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

URL = "https://live.euronext.com/en/products/equities/regulated/list"

TARGET_FRAGMENT = "/en/product_directory/data/stocks-euronext-regulated"

OUTPUT = Path("research") / "v1a3a_common_stock_filter_discovery.json"


def request_records(
    logs: list[dict[str, object]],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for item in logs:
        try:
            raw_message = item["message"]
        except KeyError:
            continue

        try:
            message = json.loads(str(raw_message))["message"]
        except (
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ):
            continue

        if message.get("method") != "Network.requestWillBeSent":
            continue

        try:
            params = message["params"]
            request = params["request"]
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


def print_requests(
    title: str,
    records: list[dict[str, object]],
) -> None:
    print()
    print("=" * 100)
    print(f"{title}: {len(records)}")
    print("=" * 100)

    for record in records:
        print()
        print(
            record["method"],
            record["url"],
        )

        if record["post_data"]:
            print("POST DATA:")
            print(record["post_data"])


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

    baseline: list[dict[str, object]] = []

    after_click: list[dict[str, object]] = []

    after_submit: list[dict[str, object]] = []

    try:
        driver.get(URL)

        time.sleep(8)

        baseline = request_records(driver.get_log("performance"))

        print_requests(
            "BASELINE REQUESTS",
            baseline,
        )

        labels = driver.find_elements(
            By.XPATH,
            ("//label[normalize-space()='Common Stock']"),
        )

        print()
        print(
            "COMMON STOCK LABELS:",
            len(labels),
        )

        if len(labels) != 1:
            raise RuntimeError("Expected exactly one Common Stock label.")

        label = labels[0]

        input_id = label.get_attribute("for")

        if not input_id:
            raise RuntimeError("Common Stock label has no 'for' attribute.")

        try:
            checkbox = driver.find_element(
                By.ID,
                input_id,
            )
        except NoSuchElementException as exc:
            raise RuntimeError(f"Could not find input #{input_id}") from exc

        print()
        print("=" * 100)
        print("COMMON STOCK CONTROL")
        print("=" * 100)

        print(
            "LABEL FOR:",
            input_id,
        )

        print("INPUT OUTER HTML:")

        print(checkbox.get_attribute("outerHTML"))

        print()
        print(
            "type:",
            checkbox.get_attribute("type"),
        )

        print(
            "name:",
            checkbox.get_attribute("name"),
        )

        print(
            "value:",
            checkbox.get_attribute("value"),
        )

        print(
            "checked before:",
            checkbox.is_selected(),
        )

        # Remove all old performance logs so anything
        # below belongs to the filter action.
        driver.get_log("performance")

        try:
            driver.execute_script(
                "arguments[0].click();",
                checkbox,
            )
        except (
            JavascriptException,
            StaleElementReferenceException,
            WebDriverException,
        ) as exc:
            raise RuntimeError("Could not activate Common Stock checkbox.") from exc

        time.sleep(5)

        print(
            "checked after:",
            checkbox.is_selected(),
        )

        after_click = request_records(driver.get_log("performance"))

        print_requests(
            "REQUESTS AFTER CHECKBOX CLICK",
            after_click,
        )

        if after_click:
            print()
            print("FILTER TRIGGERED AUTOMATICALLY.")

        else:
            print()
            print("No table request after checkbox click.")
            print("Attempting form.requestSubmit().")

            try:
                form = driver.execute_script(
                    "return arguments[0].closest('form');",
                    checkbox,
                )
            except JavascriptException as exc:
                raise RuntimeError("Could not locate filter form.") from exc

            if form is None:
                raise RuntimeError("Common Stock input has no parent form.")

            print()
            print("=" * 100)
            print("FILTER FORM")
            print("=" * 100)

            print(
                "id:",
                form.get_attribute("id"),
            )

            print(
                "action:",
                form.get_attribute("action"),
            )

            print(
                "method:",
                form.get_attribute("method"),
            )

            print()

            form_buttons = form.find_elements(
                By.CSS_SELECTOR,
                ("button, input[type='submit']"),
            )

            print(
                "FORM BUTTONS:",
                len(form_buttons),
            )

            for index, button in enumerate(
                form_buttons,
                start=1,
            ):
                try:
                    print()
                    print(f"BUTTON {index}:")
                    print(button.get_attribute("outerHTML"))
                except (
                    StaleElementReferenceException,
                    WebDriverException,
                ):
                    print(f"BUTTON {index}: <stale/unavailable>")

            driver.get_log("performance")

            try:
                driver.execute_script(
                    """
                    const form = arguments[0];

                    if (typeof form.requestSubmit === 'function') {
                        form.requestSubmit();
                    } else {
                        form.submit();
                    }
                    """,
                    form,
                )
            except (
                JavascriptException,
                StaleElementReferenceException,
                WebDriverException,
            ) as exc:
                raise RuntimeError("Could not submit filter form.") from exc

            time.sleep(8)

            after_submit = request_records(driver.get_log("performance"))

            print_requests(
                "REQUESTS AFTER FORM SUBMIT",
                after_submit,
            )

    finally:
        driver.quit()

    filtered = after_click if after_click else after_submit

    result = {
        "page": URL,
        "baseline_requests": baseline,
        "after_checkbox_click": after_click,
        "after_form_submit": after_submit,
        "filtered_requests": filtered,
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
    print("FINAL")
    print("=" * 100)

    print(
        "FILTERED REQUESTS:",
        len(filtered),
    )

    print(
        "WROTE:",
        OUTPUT,
    )


if __name__ == "__main__":
    main()
