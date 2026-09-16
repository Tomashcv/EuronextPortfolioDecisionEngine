from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

ISIN = "IT0000060886"

CHART_URL = f"https://grafici.borsaitaliana.it/interactive-chart/{ISIN}-XMIL?lang=it"

API_URL = f"https://grafici.borsaitaliana.it/api/instruments/{ISIN},XMIL,ISIN/history/period"

OUTPUT = Path("research") / "v1b0f_r1_milan_jwt_access_audit.json"

TOKEN_PATTERN = re.compile(r'token="([^"]+)"')


def main() -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
        "Accept-Language": ("it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"),
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        # ====================================================
        # WARMUP
        # ====================================================

        page = client.get(CHART_URL)

        page.raise_for_status()

        match = TOKEN_PATTERN.search(page.text)

        if match is None:
            raise RuntimeError("JWT token not found in interactive-chart page.")

        token = match.group(1)

        print("=" * 100)
        print("V1B0F-R1 — MILAN JWT ACCESS AUDIT")
        print("=" * 100)

        print()
        print(
            "INTERACTIVE CHART STATUS:",
            page.status_code,
        )

        print(
            "JWT FOUND:",
            True,
        )

        print(
            "JWT LENGTH:",
            len(token),
        )

        print(
            "COOKIE NAMES:",
            sorted(cookie.name for cookie in client.cookies.jar),
        )

        # Never print or persist the JWT itself.

        # ====================================================
        # AUTHENTICATED HISTORY REQUEST
        # ====================================================

        response = client.get(
            API_URL,
            params={
                "period": "5Y",
                "adjustment": "true",
                "add-last-price": "true",
            },
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Referer": CHART_URL,
            },
        )

        print()
        print(
            "API STATUS:",
            response.status_code,
        )

        print(
            "CONTENT TYPE:",
            response.headers.get("content-type"),
        )

        response.raise_for_status()

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError("Unexpected API payload.")

        transco = payload.get("transco")

        history = payload.get("history")

        if not isinstance(
            transco,
            dict,
        ):
            raise TypeError("Missing transco.")

        if not isinstance(
            history,
            dict,
        ):
            raise TypeError("Missing history.")

        rows = history.get("historyDt")

        if not isinstance(
            rows,
            list,
        ):
            raise TypeError("Missing historyDt.")

        print(
            "PROVIDER MIC:",
            transco.get("exchCode"),
        )

        print(
            "ROWS:",
            len(rows),
        )

        first_date = None
        last_date = None

        if rows:
            first = rows[0]
            last = rows[-1]

            if isinstance(
                first,
                dict,
            ):
                first_date = first.get("dt")

            if isinstance(
                last,
                dict,
            ):
                last_date = last.get("dt")

        print(
            "FIRST DATE:",
            first_date,
        )

        print(
            "LAST DATE:",
            last_date,
        )

        fields: list[str] = []

        if rows and isinstance(
            rows[0],
            dict,
        ):
            fields = sorted(str(key) for key in rows[0])

        print(
            "FIELDS:",
            fields,
        )

        hard_gates = {
            "warmup_http_200": page.status_code == 200,
            "jwt_found": bool(token),
            "api_http_200": response.status_code == 200,
            "provider_mic_xmil": transco.get("exchCode") == "XMIL",
            "history_nonempty": bool(rows),
            "enough_6m": len(rows) >= 126,
        }

        print()
        print("=" * 100)
        print("HARD GATES")
        print("=" * 100)

        for name, passed in hard_gates.items():
            print(
                f"{name:35s}",
                ("PASS" if passed else "FAIL"),
            )

        failed = [name for name, passed in hard_gates.items() if not passed]

        artifact: dict[
            str,
            Any,
        ] = {
            "isin": ISIN,
            "canonical_mic": "MTAA",
            "provider_mic": transco.get("exchCode"),
            "interactive_chart_status": page.status_code,
            "jwt_found": bool(token),
            "jwt_value_persisted": False,
            "jwt_length": len(token),
            "cookie_names": sorted(cookie.name for cookie in client.cookies.jar),
            "api_status": response.status_code,
            "row_count": len(rows),
            "first_date": first_date,
            "last_date": last_date,
            "fields": fields,
            "hard_gates": hard_gates,
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

        if failed:
            raise RuntimeError(f"Failed gates: {failed}")

        print()
        print("STATUS: PASS")


if __name__ == "__main__":
    main()
