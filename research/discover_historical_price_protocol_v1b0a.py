from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

TRADING_LINE_ID = "NL0000226223-XPAR"

URL = f"https://live.euronext.com/en/popout-page/getHistoricalPrice/{TRADING_LINE_ID}"

OUTPUT = Path("research") / "v1b0a_historical_price_protocol_discovery.json"


def network_records(
    logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests: dict[
        str,
        dict[str, Any],
    ] = {}

    responses: dict[
        str,
        dict[str, Any],
    ] = {}

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

        params = message.get(
            "params",
            {},
        )

        if not isinstance(
            params,
            dict,
        ):
            continue

        if method == "Network.requestWillBeSent":
            request = params.get(
                "request",
                {},
            )

            if not isinstance(
                request,
                dict,
            ):
                continue

            resource_type = str(
                params.get(
                    "type",
                    "",
                )
            )

            if resource_type not in {
                "XHR",
                "Fetch",
            }:
                continue

            request_id = str(
                params.get(
                    "requestId",
                    "",
                )
            )

            if not request_id:
                continue

            headers = request.get(
                "headers",
                {},
            )

            if not isinstance(
                headers,
                dict,
            ):
                headers = {}

            safe_headers = {
                str(key): str(value)
                for key, value in headers.items()
                if str(key).lower()
                not in {
                    "cookie",
                    "authorization",
                    "set-cookie",
                }
            }

            requests[request_id] = {
                "request_id": request_id,
                "resource_type": resource_type,
                "method": request.get("method"),
                "url": request.get("url"),
                "headers": safe_headers,
                "post_data": request.get("postData"),
            }

        elif method == "Network.responseReceived":
            response = params.get(
                "response",
                {},
            )

            if not isinstance(
                response,
                dict,
            ):
                continue

            resource_type = str(
                params.get(
                    "type",
                    "",
                )
            )

            if resource_type not in {
                "XHR",
                "Fetch",
            }:
                continue

            request_id = str(
                params.get(
                    "requestId",
                    "",
                )
            )

            if not request_id:
                continue

            responses[request_id] = {
                "status": response.get("status"),
                "mime_type": response.get("mimeType"),
                "url": response.get("url"),
            }

    result: list[dict[str, Any]] = []

    for request_id, request in requests.items():
        result.append(
            {
                **request,
                "response": responses.get(request_id),
            }
        )

    return result


def form_audit(
    driver: webdriver.Chrome,
) -> list[dict[str, Any]]:
    forms = driver.find_elements(
        By.TAG_NAME,
        "form",
    )

    result: list[dict[str, Any]] = []

    for index, form in enumerate(
        forms,
        start=1,
    ):
        controls: list[dict[str, Any]] = []

        nodes = form.find_elements(
            By.CSS_SELECTOR,
            "input, select, button",
        )

        for node in nodes:
            controls.append(
                {
                    "tag": node.tag_name,
                    "type": node.get_attribute("type"),
                    "id": node.get_attribute("id"),
                    "name": node.get_attribute("name"),
                    "value": node.get_attribute("value"),
                    "checked": (
                        node.is_selected()
                        if node.tag_name
                        in {
                            "input",
                            "option",
                        }
                        else None
                    ),
                    "outer_html": node.get_attribute("outerHTML")[:2000],
                }
            )

        result.append(
            {
                "index": index,
                "id": form.get_attribute("id"),
                "action": form.get_attribute("action"),
                "method": form.get_attribute("method"),
                "controls": controls,
            }
        )

    return result


def table_audit(
    driver: webdriver.Chrome,
) -> list[dict[str, Any]]:
    tables = driver.find_elements(
        By.TAG_NAME,
        "table",
    )

    result: list[dict[str, Any]] = []

    for index, table in enumerate(
        tables,
        start=1,
    ):
        text = table.text.strip()

        if not text:
            continue

        result.append(
            {
                "index": index,
                "id": table.get_attribute("id"),
                "class": table.get_attribute("class"),
                "text": text[:5000],
            }
        )

    return result


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

    try:
        driver.execute_cdp_cmd(
            "Network.enable",
            {},
        )

        driver.get(URL)

        time.sleep(8)

        logs = driver.get_log("performance")

        requests = network_records(logs)

        forms = form_audit(driver)

        tables = table_audit(driver)

        title = driver.title

        current_url = driver.current_url

        body_text = driver.find_element(
            By.TAG_NAME,
            "body",
        ).text

    finally:
        driver.quit()

    print("=" * 100)
    print("V1B0A — EURONEXT HISTORICAL PRICE PROTOCOL DISCOVERY")
    print("=" * 100)

    print()
    print(
        "TRADING LINE:",
        TRADING_LINE_ID,
    )

    print(
        "URL:",
        current_url,
    )

    print(
        "TITLE:",
        title,
    )

    print()
    print("=" * 100)
    print("XHR / FETCH")
    print("=" * 100)

    print(
        "COUNT:",
        len(requests),
    )

    for index, record in enumerate(
        requests,
        start=1,
    ):
        print()
        print(f"REQUEST {index}")

        print(
            record["resource_type"],
            record["method"],
            record["url"],
        )

        response = record.get("response")

        if isinstance(
            response,
            dict,
        ):
            print(
                "STATUS:",
                response.get("status"),
            )

            print(
                "MIME:",
                response.get("mime_type"),
            )

        if record.get("post_data"):
            print("POST DATA:")

            print(str(record["post_data"])[:3000])

    print()
    print("=" * 100)
    print("FORMS")
    print("=" * 100)

    print(
        "COUNT:",
        len(forms),
    )

    for form in forms:
        print()
        print(
            "FORM",
            form["index"],
        )

        print(
            "id:",
            form["id"],
        )

        print(
            "method:",
            form["method"],
        )

        print(
            "action:",
            form["action"],
        )

        for control in form["controls"]:
            print(
                "  ",
                control["tag"],
                "type=",
                control["type"],
                "id=",
                control["id"],
                "name=",
                control["name"],
                "value=",
                control["value"],
                "checked=",
                control["checked"],
            )

    print()
    print("=" * 100)
    print("TABLES")
    print("=" * 100)

    print(
        "COUNT:",
        len(tables),
    )

    for table in tables:
        print()
        print(f"TABLE {table['index']}")

        print(table["text"])

    print()
    print("=" * 100)
    print("BODY KEYWORDS")
    print("=" * 100)

    keywords = (
        "Adjusted",
        "Non-Adjusted",
        "Open",
        "High",
        "Low",
        "Close",
        "Vol.",
        "Download",
    )

    for keyword in keywords:
        print(
            f"{keyword:20s}",
            keyword.lower() in body_text.lower(),
        )

    result = {
        "trading_line_id": TRADING_LINE_ID,
        "url": current_url,
        "title": title,
        "xhr_fetch": requests,
        "forms": forms,
        "tables": tables,
        "body_keyword_presence": {
            keyword: keyword.lower() in body_text.lower() for keyword in keywords
        },
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
