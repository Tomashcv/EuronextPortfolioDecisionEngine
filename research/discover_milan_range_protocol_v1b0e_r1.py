from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options

TRADING_LINE_ID = "IT0003856405-MTAA"

URL = f"https://grafici.borsaitaliana.it/summary-chart/{TRADING_LINE_ID}?lang=it"

RANGES = (
    "1M",
    "3M",
    "6M",
    "1Y",
    "3Y",
    "5Y",
)

OUTPUT = Path("research") / "v1b0e_r1_milan_range_protocol_discovery.json"


FIND_AND_CLICK_JS = r"""
const target = arguments[0];

function walk(root) {
    const nodes = root.querySelectorAll("*");

    for (const node of nodes) {
        if (node.shadowRoot) {
            const result = walk(node.shadowRoot);

            if (result) {
                return result;
            }
        }

        const text = (
            node.innerText ||
            node.textContent ||
            ""
        ).trim();

        if (text !== target) {
            continue;
        }

        const childExact = Array.from(
            node.children || []
        ).some(
            child => (
                (
                    child.innerText ||
                    child.textContent ||
                    ""
                ).trim() === target
            )
        );

        if (childExact) {
            continue;
        }

        return node;
    }

    return null;
}

const element = walk(document);

if (!element) {
    return {
        found: false
    };
}

element.scrollIntoView({
    block: "center",
    inline: "center"
});

element.click();

return {
    found: true,
    tag: element.tagName,
    text: (
        element.innerText ||
        element.textContent ||
        ""
    ).trim(),
    className: String(
        element.className || ""
    )
};
"""


def response_body(
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
        "preview": body[:3000],
    }


def capture_api_requests(
    driver: webdriver.Chrome,
) -> list[dict[str, Any]]:
    logs = driver.get_log("performance")

    request_map: dict[
        str,
        dict[str, Any],
    ] = {}

    response_map: dict[
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

            url = str(
                request.get(
                    "url",
                    "",
                )
            )

            resource_type = str(
                params.get(
                    "type",
                    "",
                )
            )

            if (
                not request_id
                or resource_type
                not in {
                    "XHR",
                    "Fetch",
                }
                or ("grafici.borsaitaliana.it/api/" not in url)
            ):
                continue

            request_map[request_id] = {
                "request_id": request_id,
                "resource_type": resource_type,
                "method": request.get("method"),
                "url": url,
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

            url = str(
                response.get(
                    "url",
                    "",
                )
            )

            if not request_id or ("grafici.borsaitaliana.it/api/" not in url):
                continue

            response_map[request_id] = {
                "status": response.get("status"),
                "mime_type": response.get("mimeType"),
                "url": url,
            }

    output: list[dict[str, Any]] = []

    for request_id, request in request_map.items():
        response = response_map.get(request_id)

        body = None

        if response is not None:
            body = response_body(
                driver,
                request_id,
            )

        output.append(
            {
                **request,
                "response": response,
                "body": body,
            }
        )

    return output


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

    results: dict[
        str,
        Any,
    ] = {}

    try:
        driver.execute_cdp_cmd(
            "Network.enable",
            {},
        )

        driver.get(URL)

        time.sleep(6)

        # Discard the initial 1D traffic.
        driver.get_log("performance")

        print("=" * 100)
        print("V1B0E-R1 — MILAN RANGE PROTOCOL DISCOVERY")
        print("=" * 100)

        for horizon in RANGES:
            print()
            print("=" * 100)
            print(f"HORIZON {horizon}")
            print("=" * 100)

            click_result = driver.execute_script(
                FIND_AND_CLICK_JS,
                horizon,
            )

            print(
                "CLICK:",
                click_result,
            )

            time.sleep(4)

            requests = capture_api_requests(driver)

            print(
                "API REQUESTS:",
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

            results[horizon] = {
                "click": click_result,
                "requests": requests,
            }

    finally:
        driver.quit()

    artifact = {
        "trading_line_id": TRADING_LINE_ID,
        "chart_service_mic": "XMIL",
        "url": URL,
        "ranges": results,
    }

    OUTPUT.write_text(
        json.dumps(
            artifact,
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
