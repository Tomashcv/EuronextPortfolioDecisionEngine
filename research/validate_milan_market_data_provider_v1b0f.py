from __future__ import annotations

import csv
import io
import math
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

SOURCE = Path("research") / "v1b0d_cross_market_historical_coverage.tsv"

OUTPUT = Path("research") / "v1b0f_milan_provider_validation.tsv"

BORSA_BASE = "https://grafici.borsaitaliana.it/api/instruments"

EURONEXT_BASE = "https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax"


TOKEN_PATTERN = re.compile(r'token="([^"]+)"')


def parse_borsa_date(
    value: str,
) -> date:
    if len(value) != 8:
        raise ValueError(f"Unexpected Borsa date: {value!r}")

    return date(
        int(value[0:4]),
        int(value[4:6]),
        int(value[6:8]),
    )


def parse_euronext_date(
    value: str,
) -> date:
    day, month, year = (int(part) for part in value.split("/"))

    return date(
        year,
        month,
        day,
    )


def get_token(
    client: httpx.Client,
    *,
    isin: str,
) -> str:
    chart_url = f"https://grafici.borsaitaliana.it/interactive-chart/{isin}-XMIL?lang=it"

    response = client.get(
        chart_url,
        timeout=30.0,
    )

    response.raise_for_status()

    match = TOKEN_PATTERN.search(response.text)

    if match is None:
        raise RuntimeError(f"JWT token not found: {isin}")

    return match.group(1)


def get_json(
    client: httpx.Client,
    *,
    isin: str,
    adjusted: bool,
    token: str,
) -> dict[str, Any]:
    url = f"{BORSA_BASE}/{isin},XMIL,ISIN/history/period"

    chart_url = f"https://grafici.borsaitaliana.it/interactive-chart/{isin}-XMIL?lang=it"

    last_error: httpx.HTTPError | None = None

    for attempt in range(
        1,
        4,
    ):
        try:
            response = client.get(
                url,
                params={
                    "period": "5Y",
                    "adjustment": ("true" if adjusted else "false"),
                    "add-last-price": "true",
                },
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Referer": chart_url,
                },
                timeout=30.0,
            )

            response.raise_for_status()

            payload = response.json()

            if not isinstance(
                payload,
                dict,
            ):
                raise TypeError("Unexpected Borsa payload.")

            return payload

        except httpx.HTTPError as exc:
            last_error = exc

            if attempt < 3:
                time.sleep(float(attempt))

    raise RuntimeError(f"Borsa request failed: {isin}") from last_error


def borsa_rows(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    history = payload.get("history")

    if not isinstance(
        history,
        dict,
    ):
        raise TypeError("Missing Borsa history.")

    rows = history.get("historyDt")

    if not isinstance(
        rows,
        list,
    ):
        raise TypeError("Missing Borsa historyDt.")

    result: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(
            row,
            dict,
        ):
            raise TypeError("Unexpected Borsa history row.")

        result.append(row)

    return result


def euronext_rows(
    client: httpx.Client,
    *,
    trading_line_id: str,
) -> list[dict[str, str]]:
    response = client.get(
        (f"{EURONEXT_BASE}/{trading_line_id}"),
        params={
            "format": "csv",
            "decimal_separator": ".",
            "date_form": "d/m/Y",
        },
        headers={
            "Referer": (
                f"https://live.euronext.com/en/popout-page/getHistoricalPrice/{trading_line_id}"
            ),
        },
        timeout=30.0,
    )

    response.raise_for_status()

    lines = [line for line in response.text.splitlines() if line.strip()]

    if len(lines) < 4:
        return []

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[3:])),
        delimiter=";",
    )

    return list(reader)


def numeric(
    value: Any,
) -> float | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return float(text)


def close_enough(
    left: Any,
    right: Any,
    *,
    rel_tol: float = 1e-7,
    abs_tol: float = 1e-7,
) -> bool:
    left_value = numeric(left)

    right_value = numeric(right)

    if left_value is None or right_value is None:
        return left_value is None and right_value is None

    return math.isclose(
        left_value,
        right_value,
        rel_tol=rel_tol,
        abs_tol=abs_tol,
    )


def main() -> None:
    source = pd.read_csv(
        SOURCE,
        sep="\t",
    )

    sample = (
        source[source["reference_mic"] == "MTAA"]
        .sort_values("trading_line_id")
        .reset_index(drop=True)
    )

    if len(sample) != 8:
        raise RuntimeError("Expected the frozen 8-line MTAA sample.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
    }

    audit: list[dict[str, Any]] = []

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
    ) as client:
        for index, row in enumerate(
            sample.itertuples(index=False),
            start=1,
        ):
            isin = str(row.security_id)

            line_id = str(row.trading_line_id)

            print()
            print(f"[{index}/8] {line_id} | {row.display_name}")

            token = get_token(
                client,
                isin=isin,
            )

            adjusted_payload = get_json(
                client,
                isin=isin,
                adjusted=True,
                token=token,
            )

            raw_payload = get_json(
                client,
                isin=isin,
                adjusted=False,
                token=token,
            )

            adjusted_rows = borsa_rows(adjusted_payload)

            raw_rows = borsa_rows(raw_payload)

            if not adjusted_rows:
                raise RuntimeError(f"No adjusted history: {isin}")

            adjusted_dates = [parse_borsa_date(str(item["dt"])) for item in adjusted_rows]

            raw_dates = [parse_borsa_date(str(item["dt"])) for item in raw_rows]

            newest = max(adjusted_dates)

            oldest = min(adjusted_dates)

            observed_date = date(
                2026,
                9,
                14,
            )

            age_days = (observed_date - newest).days

            adjusted_map = {parse_borsa_date(str(item["dt"])): item for item in adjusted_rows}

            raw_map = {parse_borsa_date(str(item["dt"])): item for item in raw_rows}

            common_adjustment_dates = set(adjusted_map) & set(raw_map)

            adjusted_close_diff_days = sum(
                not close_enough(
                    adjusted_map[day].get("closePx"),
                    raw_map[day].get("closePx"),
                )
                for day in common_adjustment_dates
            )

            eu_rows = euronext_rows(
                client,
                trading_line_id=line_id,
            )

            eu_map = {parse_euronext_date(item["Date"]): item for item in eu_rows}

            overlap = sorted(set(adjusted_map) & set(eu_map))

            recent_comparison_days = overlap[-10:]

            price_mismatches = 0
            volume_mismatches = 0

            for day in recent_comparison_days:
                borsa = adjusted_map[day]

                euronext = eu_map[day]

                pairs = (
                    (
                        borsa.get("openPx"),
                        euronext.get("Open"),
                    ),
                    (
                        borsa.get("highPx"),
                        euronext.get("High"),
                    ),
                    (
                        borsa.get("lowPx"),
                        euronext.get("Low"),
                    ),
                    (
                        borsa.get("closePx"),
                        euronext.get("Close"),
                    ),
                )

                price_mismatches += sum(
                    not close_enough(
                        left,
                        right,
                        rel_tol=1e-6,
                        abs_tol=1e-6,
                    )
                    for left, right in pairs
                )

                volume_mismatches += int(
                    not close_enough(
                        borsa.get("qty"),
                        euronext.get("Number of Shares"),
                        rel_tol=0.0,
                        abs_tol=0.0,
                    )
                )

            transco = adjusted_payload.get("transco")

            if not isinstance(
                transco,
                dict,
            ):
                raise TypeError("Missing transco.")

            record = {
                "trading_line_id": line_id,
                "security_id": isin,
                "display_name": str(row.display_name),
                "provider_exchange_code": str(transco.get("exchCode")),
                "adjusted_rows": len(adjusted_rows),
                "raw_rows": len(raw_rows),
                "oldest": oldest.isoformat(),
                "newest": newest.isoformat(),
                "calendar_days": (newest - oldest).days,
                "fresh": age_days <= 7,
                "duplicate_adjusted_dates": (len(adjusted_dates) - len(set(adjusted_dates))),
                "same_adjusted_raw_dates": set(adjusted_dates) == set(raw_dates),
                "adjusted_close_diff_days": adjusted_close_diff_days,
                "euronext_recent_rows": len(eu_rows),
                "cross_source_overlap_days": len(overlap),
                "compared_recent_days": len(recent_comparison_days),
                "recent_ohlc_mismatches": price_mismatches,
                "recent_volume_mismatches": volume_mismatches,
                "enough_6m": len(adjusted_rows) >= 126,
                "enough_1y": len(adjusted_rows) >= 252,
                "near_5y": (newest - oldest).days >= 1750,
            }

            audit.append(record)

            print(
                "  rows:",
                record["adjusted_rows"],
            )

            print(
                "  range:",
                record["oldest"],
                "->",
                record["newest"],
            )

            print(
                "  adjusted/raw close diffs:",
                record["adjusted_close_diff_days"],
            )

            print(
                "  recent Euronext overlap:",
                record["compared_recent_days"],
            )

            print(
                "  OHLC mismatches:",
                record["recent_ohlc_mismatches"],
            )

            print(
                "  volume mismatches:",
                record["recent_volume_mismatches"],
            )

            time.sleep(0.25)

    result = pd.DataFrame(audit)

    result.to_csv(
        OUTPUT,
        sep="\t",
        index=False,
    )

    print()
    print("=" * 100)
    print("V1B0F — MILAN PROVIDER VALIDATION")
    print("=" * 100)

    print(
        "LINES:",
        len(result),
    )

    print(
        "XMIL TRANSCO:",
        int((result["provider_exchange_code"] == "XMIL").sum()),
        "/",
        len(result),
    )

    print(
        "FRESH:",
        int(result["fresh"].sum()),
        "/",
        len(result),
    )

    print(
        "ENOUGH 6M:",
        int(result["enough_6m"].sum()),
        "/",
        len(result),
    )

    print(
        "ENOUGH 1Y:",
        int(result["enough_1y"].sum()),
        "/",
        len(result),
    )

    print(
        "NEAR 5Y:",
        int(result["near_5y"].sum()),
        "/",
        len(result),
    )

    print(
        "DUPLICATE DATES:",
        int(result["duplicate_adjusted_dates"].sum()),
    )

    print(
        "LINES WITH ADJUSTMENT EFFECT:",
        int((result["adjusted_close_diff_days"] > 0).sum()),
    )

    print(
        "RECENT OHLC MISMATCHES:",
        int(result["recent_ohlc_mismatches"].sum()),
    )

    print(
        "RECENT VOLUME MISMATCHES:",
        int(result["recent_volume_mismatches"].sum()),
    )

    hard_gates = {
        "all_requests_resolved_to_xmil": (result["provider_exchange_code"] == "XMIL").all(),
        "all_lines_fresh": result["fresh"].all(),
        "all_lines_have_6m": result["enough_6m"].all(),
        "no_duplicate_dates": (result["duplicate_adjusted_dates"] == 0).all(),
        "recent_ohlc_matches_euronext": int(result["recent_ohlc_mismatches"].sum()) == 0,
        "recent_volume_matches_euronext": int(result["recent_volume_mismatches"].sum()) == 0,
    }

    print()
    print("HARD GATES")

    for name, passed in hard_gates.items():
        print(
            f"{name:45s}",
            ("PASS" if passed else "FAIL"),
        )

    print()
    print(
        "WROTE:",
        OUTPUT,
    )


if __name__ == "__main__":
    main()
