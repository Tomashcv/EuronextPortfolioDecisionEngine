from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

START_URL = "https://the-challenge.nextwise.fr"

OUTPUT = Path("research") / "v1a4c0_nextwise_network_discovery.json"


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

            # Do not persist auth/cookie material.
            safe_headers = {
                str(key): str(value)
                for key, value in headers.items()
                if str(key).lower()
                not in {
                    "authorization",
                    "cookie",
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


def main() -> None:
    options = Options()

    # Intentionally NOT headless:
    # user performs login manually.
    options.add_argument("--window-size=1500,1000")

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

        driver.get(START_URL)

        print("=" * 100)
        print("V1A4C0 — NEXTWISE NETWORK DISCOVERY")
        print("=" * 100)

        print()
        print("1. Faz login MANUALMENTE no Chrome.")
        print("2. Vai até ao ecrã onde consegues pesquisar/comprar ações.")
        print("3. NÃO escrevas passwords no terminal.")
        print()

        input("Quando estiveres no ecrã de instrumentos, carrega ENTER aqui...")

        # Forget everything associated with login/navigation.
        driver.get_log("performance")

        print()
        print("=" * 100)
        print("DISCOVERY WINDOW ACTIVE")
        print("=" * 100)

        print()
        print("Agora, no site, faz estas ações:")
        print("  - abre a pesquisa/lista de instrumentos")
        print("  - pesquisa STMicroelectronics ou STMPA")
        print("  - pesquisa GLENCORE ou JE00B4T3BW64")
        print("  - se der, pesquisa HHLA ou DE000A0S8488")
        print("  - se der, pesquisa Volkswagen ou DE0007664005")
        print("  - abre algum resultado se houver")
        print()

        input("Quando terminares essas pesquisas, carrega ENTER aqui...")

        logs = driver.get_log("performance")

        records = network_records(logs)

        current_url = driver.current_url

    finally:
        driver.quit()

    print()
    print("=" * 100)
    print("XHR / FETCH REQUESTS")
    print("=" * 100)

    print(
        "COUNT:",
        len(records),
    )

    for index, record in enumerate(
        records,
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
            text = str(post_data)

            print(
                "POST DATA:",
                text[:2000],
            )

    result = {
        "start_url": START_URL,
        "final_url": current_url,
        "security_note": (
            "Login/navigation traffic was discarded "
            "before capture. Authorization and cookie "
            "headers are excluded from the artifact."
        ),
        "requests": records,
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
