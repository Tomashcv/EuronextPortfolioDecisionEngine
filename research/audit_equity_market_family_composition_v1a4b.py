from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from euronext_pde.providers.euronext_universe import (
    build_payload,
    parse_name_fragment,
)

DISCOVERY = Path("research") / "v1a4a_equity_market_family_endpoints.json"

OUTPUT = Path("research") / "v1a4b_equity_market_family_composition_audit.json"

COMMON_STOCK_CODE = "101"

PRIMARY_FAMILIES = (
    "regulated",
    "growth",
    "access",
    "expand",
    "global_equity_market",
)

AGGREGATOR = "all_equities"

URL_MIC_RE = re.compile(r"-([A-Z0-9]{4})/?$")


def load_discovery() -> dict[str, Any]:
    data = json.loads(DISCOVERY.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise TypeError("Unexpected discovery JSON.")

    return data


def extract_endpoint(
    discovery: dict[str, Any],
    family: str,
) -> tuple[str, str]:
    entry = discovery.get(family)

    if not isinstance(
        entry,
        dict,
    ):
        raise TypeError(f"Invalid or missing discovery entry: {family}")

    page_url = str(entry["page_url"])

    requests = entry.get(
        "requests",
        [],
    )

    if not isinstance(requests, list) or len(requests) != 1:
        raise RuntimeError(f"Expected exactly one directory request for {family}.")

    request = requests[0]

    if not isinstance(
        request,
        dict,
    ):
        raise TypeError(f"Bad request entry for {family}.")

    endpoint = str(request["url"])

    return page_url, endpoint


def fetch(
    client: httpx.Client,
    *,
    endpoint: str,
    referer: str,
    common_stock_only: bool,
) -> dict[str, Any]:
    page_size = 2000

    mode = "COMMON" if common_stock_only else "RAW"

    all_rows: list[list[Any]] = []

    total: int | None = None
    start = 0
    draw = 1

    last_result: dict[str, Any] | None = None

    while total is None or start < total:
        payload = build_payload(
            start=start,
            length=page_size,
            draw=draw,
        )

        if common_stock_only:
            payload["args[issueType]"] = COMMON_STOCK_CODE
            payload["args[initialLetter]"] = ""

        print(
            f"  {mode}: start={start} length={page_size}",
            flush=True,
        )

        response: httpx.Response | None = None

        for attempt in range(
            1,
            4,
        ):
            try:
                response = client.post(
                    endpoint,
                    data=payload,
                    headers={
                        "Referer": referer,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=20.0,
                )

                response.raise_for_status()

                break

            except httpx.TransportError as exc:
                if attempt == 3:
                    raise RuntimeError(
                        "Euronext directory request "
                        "failed after 3 attempts. "
                        f"mode={mode}, "
                        f"start={start}"
                    ) from exc

                print(
                    f"    transport retry {attempt}/3: {type(exc).__name__}",
                    flush=True,
                )

                time.sleep(float(attempt))

        if response is None:
            raise RuntimeError("No HTTP response produced.")

        result = response.json()

        if not isinstance(
            result,
            dict,
        ):
            raise TypeError("Unexpected endpoint response.")

        page_rows = result.get(
            "aaData",
            [],
        )

        if not isinstance(
            page_rows,
            list,
        ):
            raise TypeError("aaData is not a list.")

        for row in page_rows:
            if not isinstance(
                row,
                list,
            ):
                raise TypeError("Directory row is not a list.")

        page_total = int(result["iTotalRecords"])

        if total is None:
            total = page_total

        elif page_total != total:
            raise RuntimeError(
                f"Directory total changed during pagination: {total} -> {page_total}"
            )

        print(
            f"    received={len(page_rows)} total={total}",
            flush=True,
        )

        if not page_rows and start < total:
            raise RuntimeError("Received an empty page before reaching directory total.")

        all_rows.extend(page_rows)

        start += len(page_rows)

        draw += 1
        last_result = result

    if total is None or last_result is None:
        raise RuntimeError("Directory acquisition produced no response.")

    merged = dict(last_result)

    merged["aaData"] = all_rows
    merged["iTotalRecords"] = total
    merged["iTotalDisplayRecords"] = total

    return merged


def rows(
    payload: dict[str, Any],
) -> list[list[Any]]:
    value = payload.get(
        "aaData",
        [],
    )

    if not isinstance(
        value,
        list,
    ):
        raise TypeError("aaData is not a list.")

    result: list[list[Any]] = []

    for row in value:
        if not isinstance(
            row,
            list,
        ):
            raise TypeError("Directory row is not a list.")

        result.append(row)

    return result


def trading_line_id(
    row: list[Any],
) -> str:
    isin = str(row[1]).strip()

    _, product_url = parse_name_fragment(str(row[0]))

    match = URL_MIC_RE.search(product_url)

    if match is None:
        raise RuntimeError(f"Could not extract MIC from {product_url}")

    return f"{isin}-{match.group(1)}"


def reference_mic(
    row: list[Any],
) -> str:
    line_id = trading_line_id(row)

    return line_id.rsplit(
        "-",
        maxsplit=1,
    )[1]


def row_record(
    row: list[Any],
) -> dict[str, str]:
    name, product_url = parse_name_fragment(str(row[0]))

    return {
        "trading_line_id": trading_line_id(row),
        "company_name": name,
        "isin": str(row[1]).strip(),
        "ticker": str(row[2]).strip(),
        "reference_mic": reference_mic(row),
        "product_url": product_url,
    }


def endpoint_mics(
    endpoint: str,
) -> list[str]:
    query = parse_qs(urlparse(endpoint).query)

    raw = query.get(
        "mics",
        [""],
    )[0]

    return [value.strip() for value in raw.split(",") if value.strip()]


def main() -> None:
    discovery = load_discovery()

    families = (
        *PRIMARY_FAMILIES,
        AGGREGATOR,
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
    }

    audit: dict[str, Any] = {}

    with httpx.Client(
        headers=headers,
        timeout=45.0,
        follow_redirects=True,
    ) as client:
        for family in families:
            page_url, endpoint = extract_endpoint(
                discovery,
                family,
            )

            raw_payload = fetch(
                client,
                endpoint=endpoint,
                referer=page_url,
                common_stock_only=False,
            )

            common_payload = fetch(
                client,
                endpoint=endpoint,
                referer=page_url,
                common_stock_only=True,
            )

            raw_rows = rows(raw_payload)

            common_rows = rows(common_payload)

            raw_records = [row_record(row) for row in raw_rows]

            common_records = [row_record(row) for row in common_rows]

            raw_ids = {record["trading_line_id"] for record in raw_records}

            common_ids = {record["trading_line_id"] for record in common_records}

            raw_total = int(raw_payload["iTotalRecords"])

            common_total = int(common_payload["iTotalRecords"])

            gates = {
                "raw_full_response": len(raw_rows) == raw_total,
                "common_full_response": len(common_rows) == common_total,
                "raw_ids_unique": len(raw_ids) == len(raw_rows),
                "common_ids_unique": len(common_ids) == len(common_rows),
                "common_subset_raw": common_ids.issubset(raw_ids),
            }

            audit[family] = {
                "page_url": page_url,
                "endpoint": endpoint,
                "endpoint_mics": endpoint_mics(endpoint),
                "raw_total": raw_total,
                "common_stock_total": common_total,
                "non_common_stock_total": (raw_total - common_total),
                "raw_records": raw_records,
                "common_records": common_records,
                "gates": gates,
            }

    print("=" * 100)
    print("V1A4B — EQUITY MARKET FAMILY COMPOSITION AUDIT")
    print("=" * 100)

    print()
    print(f"{'FAMILY':24s} {'RAW':>8s} {'COMMON':>8s} {'OTHER':>8s}")

    print("-" * 55)

    for family in families:
        entry = audit[family]

        print(
            f"{family:24s} "
            f"{entry['raw_total']:8d} "
            f"{entry['common_stock_total']:8d} "
            f"{entry['non_common_stock_total']:8d}"
        )

    # --------------------------------------------------------
    # CROSS-FAMILY OVERLAPS
    # --------------------------------------------------------

    line_to_families: dict[
        str,
        list[str],
    ] = defaultdict(list)

    line_records: dict[
        str,
        dict[str, str],
    ] = {}

    for family in PRIMARY_FAMILIES:
        for record in audit[family]["raw_records"]:
            line_id = record["trading_line_id"]

            line_to_families[line_id].append(family)

            line_records[line_id] = record

    overlaps = {
        line_id: family_list
        for line_id, family_list in line_to_families.items()
        if len(family_list) > 1
    }

    print()
    print("=" * 100)
    print("CROSS-FAMILY OVERLAPS (PRIMARY FAMILY DIRECTORIES)")
    print("=" * 100)

    print(
        "OVERLAPPING TRADING LINES:",
        len(overlaps),
    )

    for line_id in sorted(overlaps)[:50]:
        record = line_records[line_id]

        print(
            f"{line_id} | "
            f"{record['company_name']} | "
            f"{record['ticker']} | "
            f"{','.join(overlaps[line_id])}"
        )

    # --------------------------------------------------------
    # FAMILY UNION VS ALL EQUITIES
    # --------------------------------------------------------

    primary_union = set(line_to_families)

    all_records = audit[AGGREGATOR]["raw_records"]

    all_map = {record["trading_line_id"]: record for record in all_records}

    all_ids = set(all_map)

    all_only = sorted(all_ids - primary_union)

    primary_only = sorted(primary_union - all_ids)

    print()
    print("=" * 100)
    print("PRIMARY FAMILY UNION VS ALL EQUITIES")
    print("=" * 100)

    print(
        "PRIMARY FAMILY UNION:",
        len(primary_union),
    )

    print(
        "ALL EQUITIES:",
        len(all_ids),
    )

    print(
        "ALL-EQUITIES ONLY:",
        len(all_only),
    )

    print(
        "PRIMARY-UNION ONLY:",
        len(primary_only),
    )

    # --------------------------------------------------------
    # RESIDUAL MIC DISTRIBUTION
    # --------------------------------------------------------

    residual_mics = Counter(all_map[line_id]["reference_mic"] for line_id in all_only)

    print()
    print("=" * 100)
    print("ALL-EQUITIES-ONLY MIC DISTRIBUTION")
    print("=" * 100)

    if not residual_mics:
        print("NONE")
    else:
        for mic, count in sorted(residual_mics.items()):
            print(f"{mic:8s} {count:6d}")

    print()
    print("=" * 100)
    print("FIRST 100 ALL-EQUITIES-ONLY LINES")
    print("=" * 100)

    for line_id in all_only[:100]:
        record = all_map[line_id]

        print(
            f"{line_id} | {record['company_name']} | {record['ticker']} | {record['reference_mic']}"
        )

    if primary_only:
        print()
        print("=" * 100)
        print("PRIMARY-FAMILY LINES MISSING FROM ALL EQUITIES")
        print("=" * 100)

        for line_id in primary_only[:100]:
            record = line_records[line_id]

            print(
                f"{line_id} | "
                f"{record['company_name']} | "
                f"{record['ticker']} | "
                f"{record['reference_mic']}"
            )

    # --------------------------------------------------------
    # COMMON-STOCK UNION COMPARISON
    # --------------------------------------------------------

    primary_common_ids: set[str] = set()

    for family in PRIMARY_FAMILIES:
        primary_common_ids.update(
            record["trading_line_id"] for record in audit[family]["common_records"]
        )

    all_common_ids = {record["trading_line_id"] for record in audit[AGGREGATOR]["common_records"]}

    print()
    print("=" * 100)
    print("COMMON STOCK UNION COMPARISON")
    print("=" * 100)

    print(
        "PRIMARY COMMON-STOCK UNION:",
        len(primary_common_ids),
    )

    print(
        "ALL-EQUITIES COMMON STOCK:",
        len(all_common_ids),
    )

    print(
        "ALL COMMON ONLY:",
        len(all_common_ids - primary_common_ids),
    )

    print(
        "PRIMARY COMMON ONLY:",
        len(primary_common_ids - all_common_ids),
    )

    # --------------------------------------------------------
    # HARD GATES
    # --------------------------------------------------------

    hard_gates: dict[str, bool] = {}

    for family in families:
        for gate_name, passed in audit[family]["gates"].items():
            hard_gates[f"{family}_{gate_name}"] = bool(passed)

    failed = [name for name, passed in hard_gates.items() if not passed]

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:55s}",
            ("PASS" if passed else "FAIL"),
        )

    result = {
        "families": audit,
        "primary_family_union_count": len(primary_union),
        "cross_family_overlap_count": len(overlaps),
        "cross_family_overlaps": overlaps,
        "all_equities_count": len(all_ids),
        "all_equities_only_count": len(all_only),
        "all_equities_only_ids": all_only,
        "all_equities_only_mic_counts": dict(sorted(residual_mics.items())),
        "primary_union_only_count": len(primary_only),
        "primary_union_only_ids": primary_only,
        "primary_common_stock_union_count": len(primary_common_ids),
        "all_equities_common_stock_count": len(all_common_ids),
        "hard_gates": hard_gates,
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
    print(
        "WROTE:",
        OUTPUT,
    )

    print()

    if failed:
        print("STATUS: FAIL")

        raise RuntimeError(f"Failed gates: {failed}")

    print("STATUS: PASS")


if __name__ == "__main__":
    main()
