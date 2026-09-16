from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

ISIN = "IT0000060886"

CHART_URL = f"https://grafici.borsaitaliana.it/summary-chart/{ISIN}-MTAA?lang=it"

API_URL = f"https://grafici.borsaitaliana.it/api/instruments/{ISIN},XMIL,ISIN/history/period"

PARAMS = {
    "period": "5Y",
    "adjustment": "true",
    "add-last-price": "true",
}

OUTPUT = Path("research") / "v1b0f_r0_milan_access_boundary_audit.json"


def request_headers(
    user_agent: str,
) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Referer": CHART_URL,
    }


def summarize_httpx(
    response: httpx.Response,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "body_bytes": len(response.content),
    }

    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError:
            result["json"] = False

            return result

        result["json"] = True

        if isinstance(
            payload,
            dict,
        ):
            transco = payload.get("transco")

            history = payload.get("history")

            if isinstance(
                transco,
                dict,
            ):
                result["exchange_code"] = transco.get("exchCode")

            if isinstance(
                history,
                dict,
            ):
                rows = history.get("historyDt")

                if isinstance(
                    rows,
                    list,
                ):
                    result["rows"] = len(rows)

                    if rows:
                        first = rows[0]
                        last = rows[-1]

                        if isinstance(
                            first,
                            dict,
                        ):
                            result["first_date"] = first.get("dt")

                        if isinstance(
                            last,
                            dict,
                        ):
                            result["last_date"] = last.get("dt")

    return result


def print_result(
    label: str,
    result: dict[str, Any],
) -> None:
    print()
    print("=" * 100)
    print(label)
    print("=" * 100)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


def main() -> None:
    standard_ua = (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152 Safari/537.36"
    )

    results: dict[
        str,
        Any,
    ] = {}

    # ========================================================
    # A — BARE HTTPX
    # ========================================================

    with httpx.Client(
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        response = client.get(
            API_URL,
            params=PARAMS,
            headers=request_headers(standard_ua),
        )

        result = summarize_httpx(response)

        results["a_bare_httpx"] = result

        print_result(
            "A — BARE HTTPX",
            result,
        )

    # ========================================================
    # B — HTTPX PAGE BOOTSTRAP
    # ========================================================

    with httpx.Client(
        follow_redirects=True,
        timeout=30.0,
        headers={
            "User-Agent": standard_ua,
        },
    ) as client:
        page = client.get(CHART_URL)

        response = client.get(
            API_URL,
            params=PARAMS,
            headers={
                "Accept": "application/json",
                "Referer": CHART_URL,
            },
        )

        result = summarize_httpx(response)

        result["page_status"] = page.status_code

        result["cookie_names"] = sorted(cookie.name for cookie in client.cookies.jar)

        results["b_httpx_page_bootstrap"] = result

        print_result(
            "B — HTTPX AFTER PAGE VISIT",
            result,
        )

    # ========================================================
    # CHROME BOOTSTRAP
    # ========================================================

    options = Options()

    options.add_argument("--headless=new")

    options.add_argument("--window-size=1600,1200")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(CHART_URL)

        time.sleep(6)

        browser_ua = str(driver.execute_script("return navigator.userAgent;"))

        cookies = driver.get_cookies()

        safe_cookie_names = sorted(str(cookie["name"]) for cookie in cookies)

        print()
        print(
            "CHROME COOKIE NAMES:",
            safe_cookie_names,
        )

        # ====================================================
        # C — HTTPX + CHROME COOKIES
        # ====================================================

        with httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": browser_ua,
            },
        ) as client:
            for cookie in cookies:
                client.cookies.set(
                    str(cookie["name"]),
                    str(cookie["value"]),
                    domain=str(
                        cookie.get(
                            "domain",
                            "",
                        )
                    ),
                    path=str(
                        cookie.get(
                            "path",
                            "/",
                        )
                    ),
                )

            response = client.get(
                API_URL,
                params=PARAMS,
                headers={
                    "Accept": "application/json",
                    "Referer": CHART_URL,
                },
            )

            result = summarize_httpx(response)

            result["chrome_cookie_names"] = safe_cookie_names

            results["c_httpx_with_chrome_cookies"] = result

            print_result(
                "C — HTTPX + CHROME COOKIES",
                result,
            )

        # ====================================================
        # D — FETCH INSIDE CHROME
        # ====================================================

        full_api_url = str(
            httpx.URL(
                API_URL,
                params=PARAMS,
            )
        )

        browser_result = driver.execute_async_script(
            """
const url = arguments[0];
const done = arguments[arguments.length - 1];

fetch(
    url,
    {
        method: "GET",
        credentials: "include",
        headers: {
            "Accept": "application/json"
        }
    }
)
.then(async response => {
    const text = await response.text();

    done({
        status: response.status,
        contentType:
            response.headers.get(
                "content-type"
            ),
        text: text
    });
})
.catch(error => {
    done({
        error: String(error)
    });
});
""",
            full_api_url,
        )

        if not isinstance(
            browser_result,
            dict,
        ):
            raise TypeError("Unexpected browser fetch result.")

        safe_browser: dict[
            str,
            Any,
        ] = {
            "status": browser_result.get("status"),
            "content_type": browser_result.get("contentType"),
        }

        text = browser_result.get("text")

        if isinstance(
            text,
            str,
        ):
            safe_browser["body_bytes"] = len(text.encode("utf-8"))

            try:
                payload = json.loads(text)

            except json.JSONDecodeError:
                payload = None

            if isinstance(
                payload,
                dict,
            ):
                transco = payload.get("transco")

                history = payload.get("history")

                if isinstance(
                    transco,
                    dict,
                ):
                    safe_browser["exchange_code"] = transco.get("exchCode")

                if isinstance(
                    history,
                    dict,
                ):
                    history_rows = history.get("historyDt")

                    if isinstance(
                        history_rows,
                        list,
                    ):
                        safe_browser["rows"] = len(history_rows)

                        if history_rows:
                            first = history_rows[0]

                            last = history_rows[-1]

                            if isinstance(
                                first,
                                dict,
                            ):
                                safe_browser["first_date"] = first.get("dt")

                            if isinstance(
                                last,
                                dict,
                            ):
                                safe_browser["last_date"] = last.get("dt")

        if "error" in browser_result:
            safe_browser["error"] = browser_result["error"]

        results["d_browser_fetch"] = safe_browser

        print_result(
            "D — FETCH INSIDE CHROME",
            safe_browser,
        )

    finally:
        driver.quit()

    # ========================================================
    # INTERPRETATION
    # ========================================================

    statuses = {
        key: value.get("status")
        for key, value in results.items()
        if isinstance(
            value,
            dict,
        )
    }

    if statuses.get("a_bare_httpx") == 200:
        boundary = "DIRECT_HTTP_AVAILABLE"

    elif statuses.get("b_httpx_page_bootstrap") == 200:
        boundary = "HTTP_PAGE_BOOTSTRAP_REQUIRED"

    elif statuses.get("c_httpx_with_chrome_cookies") == 200:
        boundary = "BROWSER_COOKIE_BOOTSTRAP_REQUIRED"

    elif statuses.get("d_browser_fetch") == 200:
        boundary = "BROWSER_CONTEXT_REQUIRED"

    else:
        boundary = "UNRESOLVED"

    print()
    print("=" * 100)
    print(
        "ACCESS BOUNDARY:",
        boundary,
    )
    print("=" * 100)

    artifact = {
        "isin": ISIN,
        "canonical_mic": "MTAA",
        "provider_mic": "XMIL",
        "cookie_values_persisted": False,
        "results": results,
        "access_boundary": boundary,
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
    print(
        "WROTE:",
        OUTPUT,
    )


if __name__ == "__main__":
    main()
