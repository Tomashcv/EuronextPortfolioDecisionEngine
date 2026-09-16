from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from audit_equity_market_family_composition_v1a4b import (
    AGGREGATOR,
    PRIMARY_FAMILIES,
    endpoint_mics,
    extract_endpoint,
    fetch,
    load_discovery,
    row_record,
    rows,
    trading_line_id,
)

OUTPUT = Path("research") / "v1a4b_r1_equity_market_family_composition_audit.json"


def endpoint_for_mic(
    endpoint: str,
    mic: str,
) -> str:
    parts = urlsplit(endpoint)

    query = dict(
        parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
    )

    query["mics"] = mic

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def fetch_all_equities_by_mic(
    *,
    endpoint: str,
    referer: str,
    common_stock_only: bool,
    headers: dict[str, str],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
]:
    mics = endpoint_mics(endpoint)

    mode = "COMMON" if common_stock_only else "RAW"

    unique_rows: dict[
        str,
        list[Any],
    ] = {}

    per_mic: dict[
        str,
        int,
    ] = {}

    duplicate_hits = 0

    conflicting_identity_ids: set[str] = set()

    for index, mic in enumerate(
        mics,
        start=1,
    ):
        print()
        print(
            f"  ALL_EQUITIES {mode}: MIC={mic} ({index}/{len(mics)})",
            flush=True,
        )

        mic_endpoint = endpoint_for_mic(
            endpoint,
            mic,
        )

        # Fresh connection for every MIC.
        # This deliberately avoids depending on
        # connection/session state.
        with httpx.Client(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            payload = fetch(
                client,
                endpoint=mic_endpoint,
                referer=referer,
                common_stock_only=(common_stock_only),
            )

        page_rows = rows(payload)

        per_mic[mic] = len(page_rows)

        for row in page_rows:
            line_id = trading_line_id(row)

            previous = unique_rows.get(line_id)

            if previous is None:
                unique_rows[line_id] = row

                continue

            duplicate_hits += 1

            # A multi-MIC trading line may legitimately
            # be returned by more than one MIC shard.
            # Its economic identity must nevertheless
            # remain identical.
            if row_record(previous) != row_record(row):
                conflicting_identity_ids.add(line_id)

        # Be polite to the public endpoint and reduce
        # the chance of transient throttling.
        time.sleep(0.25)

    merged_rows = list(unique_rows.values())

    merged_payload: dict[
        str,
        Any,
    ] = {
        "iTotalRecords": len(merged_rows),
        "iTotalDisplayRecords": len(merged_rows),
        "aaData": merged_rows,
    }

    diagnostics: dict[
        str,
        Any,
    ] = {
        "mode": mode,
        "queried_mics": mics,
        "per_mic_row_counts": per_mic,
        "unique_trading_lines": len(merged_rows),
        "duplicate_shard_hits": duplicate_hits,
        "conflicting_identity_ids": sorted(conflicting_identity_ids),
    }

    return (
        merged_payload,
        diagnostics,
    )


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

    audit: dict[
        str,
        Any,
    ] = {}

    aggregator_diagnostics: dict[
        str,
        Any,
    ] = {}

    # ========================================================
    # ACQUISITION
    # ========================================================

    for family in families:
        print()
        print("=" * 100)
        print(f"ACQUIRE {family.upper()}")
        print("=" * 100)

        page_url, endpoint = extract_endpoint(
            discovery,
            family,
        )

        if family == AGGREGATOR:
            (
                raw_payload,
                raw_diagnostics,
            ) = fetch_all_equities_by_mic(
                endpoint=endpoint,
                referer=page_url,
                common_stock_only=False,
                headers=headers,
            )

            (
                common_payload,
                common_diagnostics,
            ) = fetch_all_equities_by_mic(
                endpoint=endpoint,
                referer=page_url,
                common_stock_only=True,
                headers=headers,
            )

            aggregator_diagnostics = {
                "raw": raw_diagnostics,
                "common": common_diagnostics,
            }

        else:
            # Fresh client per family. No session
            # semantics are required by these endpoints.
            with httpx.Client(
                headers=headers,
                timeout=30.0,
                follow_redirects=True,
            ) as client:
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
            "non_common_stock_total": raw_total - common_total,
            "raw_records": raw_records,
            "common_records": common_records,
            "gates": gates,
        }

    # ========================================================
    # FAMILY COUNTS
    # ========================================================

    print()
    print("=" * 100)
    print("V1A4B-R1 — EQUITY MARKET FAMILY COMPOSITION")
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

    # ========================================================
    # PRIMARY-FAMILY OVERLAPS
    # ========================================================

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
    print("CROSS-FAMILY OVERLAPS")
    print("=" * 100)

    print(
        "OVERLAPPING TRADING LINES:",
        len(overlaps),
    )

    for line_id in sorted(overlaps)[:100]:
        record = line_records[line_id]

        print(
            f"{line_id} | "
            f"{record['company_name']} | "
            f"{record['ticker']} | "
            f"{','.join(overlaps[line_id])}"
        )

    # ========================================================
    # PRIMARY UNION VS ALL EQUITIES
    # ========================================================

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

    residual_mics = Counter(all_map[line_id]["reference_mic"] for line_id in all_only)

    print()
    print("=" * 100)
    print("ALL-EQUITIES-ONLY MIC DISTRIBUTION")
    print("=" * 100)

    if residual_mics:
        for mic, count in sorted(residual_mics.items()):
            print(f"{mic:8s} {count:6d}")
    else:
        print("NONE")

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
        print("PRIMARY-UNION LINES MISSING FROM ALL EQUITIES")
        print("=" * 100)

        for line_id in primary_only[:100]:
            record = line_records[line_id]

            print(
                f"{line_id} | "
                f"{record['company_name']} | "
                f"{record['ticker']} | "
                f"{record['reference_mic']}"
            )

    # ========================================================
    # COMMON-STOCK UNION
    # ========================================================

    primary_common_ids: set[str] = set()

    for family in PRIMARY_FAMILIES:
        primary_common_ids.update(
            record["trading_line_id"] for record in audit[family]["common_records"]
        )

    all_common_ids = {record["trading_line_id"] for record in audit[AGGREGATOR]["common_records"]}

    all_common_only = all_common_ids - primary_common_ids

    primary_common_only = primary_common_ids - all_common_ids

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
        len(all_common_only),
    )

    print(
        "PRIMARY COMMON ONLY:",
        len(primary_common_only),
    )

    # ========================================================
    # ALL-EQUITIES SHARD DIAGNOSTICS
    # ========================================================

    print()
    print("=" * 100)
    print("ALL-EQUITIES SHARD DIAGNOSTICS")
    print("=" * 100)

    for mode in (
        "raw",
        "common",
    ):
        diag = aggregator_diagnostics[mode]

        print()
        print(mode.upper())

        print(
            "UNIQUE TRADING LINES:",
            diag["unique_trading_lines"],
        )

        print(
            "DUPLICATE SHARD HITS:",
            diag["duplicate_shard_hits"],
        )

        print(
            "IDENTITY CONFLICTS:",
            len(diag["conflicting_identity_ids"]),
        )

        print("PER-MIC COUNTS:")

        for mic, count in sorted(diag["per_mic_row_counts"].items()):
            print(f"  {mic:8s} {count:6d}")

    # ========================================================
    # HARD GATES
    # ========================================================

    hard_gates: dict[
        str,
        bool,
    ] = {}

    for family in families:
        for gate_name, passed in audit[family]["gates"].items():
            hard_gates[f"{family}_{gate_name}"] = bool(passed)

    hard_gates["all_equities_raw_no_identity_conflicts"] = not aggregator_diagnostics["raw"][
        "conflicting_identity_ids"
    ]

    hard_gates["all_equities_common_no_identity_conflicts"] = not aggregator_diagnostics["common"][
        "conflicting_identity_ids"
    ]

    hard_gates["primary_union_subset_all_equities"] = primary_union.issubset(all_ids)

    hard_gates["primary_common_subset_all_common"] = primary_common_ids.issubset(all_common_ids)

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:60s}",
            ("PASS" if passed else "FAIL"),
        )

    failed = [name for name, passed in hard_gates.items() if not passed]

    result = {
        "status": ("PASS" if not failed else "FAIL"),
        "families": audit,
        "all_equities_shard_diagnostics": aggregator_diagnostics,
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
        "all_common_only_count": len(all_common_only),
        "primary_common_only_count": len(primary_common_only),
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
