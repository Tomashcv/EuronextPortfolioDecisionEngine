from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

TRADING_LINE_ID = "IT0003856405-MTAA"

URL = f"https://grafici.borsaitaliana.it/summary-chart/{TRADING_LINE_ID}?lang=it"

OUTPUT = Path("research") / "v1b0e_milan_chart_protocol_discovery.json"


def safe_body(
    driver: webdriver.Chrome,
    request_id: str,
) -> dict[str, Any]:
    try:
        result = driver.execute_cdp_cmd(
            "Network.getResponseBody",
            {
                "requestId": request_id,
            },
        )
    except WebDriverException as exc:
        return {
            "available": False,
            "error": type(exc).__name__,
        }

    body = result.get(
        "body",
        "",
    )

    if not isinstance(
        body,
        str,
    ):
        body = str(body)

    return {
        "available": True,
        "base64_encoded": bool(
            result.get(
                "base64Encoded",
                False,
            )
        ),
        "length": len(body),
        "preview": body[:10000],
    }


def collect_network(
    driver: webdriver.Chrome,
) -> list[dict[str, Any]]:
    logs = driver.get_log("performance")

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

            request_id = str(
                params.get(
                    "requestId",
                    "",
                )
            )

            if not request_id:
                continue

            requests[request_id] = {
                "request_id": request_id,
                "resource_type": str(
                    params.get(
                        "type",
                        "",
                    )
                ),
                "method": request.get("method"),
                "url": request.get("url"),
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
        url = str(request.get("url", ""))

        if not any(
            domain in url
            for domain in (
                "borsaitaliana.it",
                "euronext.com",
            )
        ):
            continue

        response = responses.get(request_id)

        body: (
            dict[
                str,
                Any,
            ]
            | None
        ) = None

        resource_type = request["resource_type"]

        if response is not None and resource_type in {
            "XHR",
            "Fetch",
        }:
            body = safe_body(
                driver,
                request_id,
            )

        result.append(
            {
                **request,
                "response": response,
                "body": body,
            }
        )

    return result


def main() -> None:
    options = Options()

    options.add_argument("--headless=new")

    options.add_argument("--window-size=1600,1200")

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

        time.sleep(10)

        title = driver.title

        current_url = driver.current_url

        elements = driver.find_elements(
            By.CSS_SELECTOR,
            "button, a, [role='button']",
        )

        controls: list[dict[str, str]] = []

        seen: set[tuple[str, str]] = set()

        for element in elements:
            text = element.text.strip()

            aria = (element.get_attribute("aria-label") or "").strip()

            if not text and not aria:
                continue

            key = (
                text,
                aria,
            )

            if key in seen:
                continue

            seen.add(key)

            controls.append(
                {
                    "text": text,
                    "aria_label": aria,
                    "tag": element.tag_name,
                    "class": (element.get_attribute("class") or ""),
                }
            )

        network = collect_network(driver)

        body_text = driver.find_element(
            By.TAG_NAME,
            "body",
        ).text

    finally:
        driver.quit()

    print("=" * 100)
    print("V1B0E — MILAN CHART PROTOCOL DISCOVERY")
    print("=" * 100)

    print()
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
    print("CONTROLS")
    print("=" * 100)

    for control in controls:
        print(
            repr(control["text"]),
            "| aria=",
            repr(control["aria_label"]),
            "| class=",
            control["class"],
        )

    print()
    print("=" * 100)
    print("NETWORK")
    print("=" * 100)

    for index, record in enumerate(
        network,
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

        post_data = record.get("post_data")

        if post_data:
            print(
                "POST DATA:",
                str(post_data)[:3000],
            )

        body = record.get("body")

        if isinstance(
            body,
            dict,
        ) and body.get("available"):
            print(
                "BODY LENGTH:",
                body.get("length"),
            )

            print("BODY PREVIEW:")

            print(
                body.get(
                    "preview",
                    "",
                )
            )

    print()
    print("=" * 100)
    print("BODY TEXT PREVIEW")
    print("=" * 100)

    print(body_text[:5000])

    result = {
        "trading_line_id": TRADING_LINE_ID,
        "url": current_url,
        "title": title,
        "controls": controls,
        "network": network,
        "body_text_preview": body_text[:10000],
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
