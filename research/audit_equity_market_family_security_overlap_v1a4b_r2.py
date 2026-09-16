from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

SOURCE = Path("research") / "v1a4b_r1_equity_market_family_composition_audit.json"

OUTPUT = Path("research") / "v1a4b_r2_security_overlap_audit.json"

PRIMARY_FAMILIES = (
    "regulated",
    "growth",
    "access",
    "expand",
    "global_equity_market",
)

AGGREGATOR = "all_equities"

AUXILIARY_MIC_LABELS = {
    "ETLX": "EuroTLX",
    "MTAH": "Trading After Hours",
    "XPMC": "Euronext Paris Multi-Currency Trading",
}


def load_source() -> dict[str, Any]:
    data = json.loads(
        SOURCE.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(
        data,
        dict,
    ):
        raise TypeError("Unexpected R1 artifact.")

    return data


def records(
    data: dict[str, Any],
    family: str,
    field: str,
) -> list[dict[str, str]]:
    families = data.get("families")

    if not isinstance(
        families,
        dict,
    ):
        raise TypeError("Missing families mapping.")

    family_data = families.get(family)

    if not isinstance(
        family_data,
        dict,
    ):
        raise TypeError(f"Missing family: {family}")

    value = family_data.get(field)

    if not isinstance(
        value,
        list,
    ):
        raise TypeError(f"Missing {family}.{field}")

    result: list[dict[str, str]] = []

    for item in value:
        if not isinstance(
            item,
            dict,
        ):
            raise TypeError("Record is not a mapping.")

        result.append({str(key): str(val) for key, val in item.items()})

    return result


def line_map(
    values: list[dict[str, str]],
) -> dict[
    str,
    dict[str, str],
]:
    return {record["trading_line_id"]: record for record in values}


def security_ids(
    values: list[dict[str, str]],
) -> set[str]:
    return {record["isin"] for record in values}


def main() -> None:
    data = load_source()

    # ========================================================
    # RAW PRIMARY UNION
    # ========================================================

    primary_raw_records: list[dict[str, str]] = []

    primary_common_records: list[dict[str, str]] = []

    for family in PRIMARY_FAMILIES:
        primary_raw_records.extend(
            records(
                data,
                family,
                "raw_records",
            )
        )

        primary_common_records.extend(
            records(
                data,
                family,
                "common_records",
            )
        )

    all_raw_records = records(
        data,
        AGGREGATOR,
        "raw_records",
    )

    all_common_records = records(
        data,
        AGGREGATOR,
        "common_records",
    )

    primary_raw_lines = line_map(primary_raw_records)

    primary_common_lines = line_map(primary_common_records)

    all_raw_lines = line_map(all_raw_records)

    all_common_lines = line_map(all_common_records)

    primary_raw_ids = set(primary_raw_lines)

    primary_common_ids = set(primary_common_lines)

    all_raw_ids = set(all_raw_lines)

    all_common_ids = set(all_common_lines)

    # ========================================================
    # LINE DIFFERENCES
    # ========================================================

    all_only_ids = all_raw_ids - primary_raw_ids

    primary_only_ids = primary_raw_ids - all_raw_ids

    all_common_only_ids = all_common_ids - primary_common_ids

    primary_common_only_ids = primary_common_ids - all_common_ids

    # ========================================================
    # SECURITY-LEVEL UNIONS
    # ========================================================

    primary_raw_securities = security_ids(primary_raw_records)

    all_raw_securities = security_ids(all_raw_records)

    primary_common_securities = security_ids(primary_common_records)

    all_common_securities = security_ids(all_common_records)

    all_only_records = [all_raw_lines[line_id] for line_id in sorted(all_only_ids)]

    all_common_only_records = [all_common_lines[line_id] for line_id in sorted(all_common_only_ids)]

    # ========================================================
    # AUXILIARY MIC SECURITY OVERLAP
    # ========================================================

    by_mic: dict[
        str,
        list[dict[str, str]],
    ] = defaultdict(list)

    for record in all_only_records:
        by_mic[record["reference_mic"]].append(record)

    mic_audit: dict[
        str,
        dict[str, Any],
    ] = {}

    print("=" * 100)
    print("V1A4B-R2 — SECURITY-LEVEL OVERLAP AUDIT")
    print("=" * 100)

    print()
    print(
        "PRIMARY RAW LINES:",
        len(primary_raw_ids),
    )

    print(
        "PRIMARY RAW SECURITIES:",
        len(primary_raw_securities),
    )

    print()
    print(
        "ALL-EQUITIES RAW LINES:",
        len(all_raw_ids),
    )

    print(
        "ALL-EQUITIES RAW SECURITIES:",
        len(all_raw_securities),
    )

    print()
    print(
        "ALL-EQUITIES-ONLY LINES:",
        len(all_only_ids),
    )

    print(
        "PRIMARY-ONLY LINES:",
        len(primary_only_ids),
    )

    print()
    print("=" * 100)
    print("AUXILIARY MIC SECURITY OVERLAP")
    print("=" * 100)

    print()
    print(f"{'MIC':8s} {'LINES':>8s} {'SEC':>8s} {'IN_PRIMARY':>12s} {'NEW_SEC':>10s}")

    print("-" * 52)

    for mic in sorted(by_mic):
        mic_records = by_mic[mic]

        mic_securities = {record["isin"] for record in mic_records}

        existing = mic_securities & primary_raw_securities

        new = mic_securities - primary_raw_securities

        mic_audit[mic] = {
            "label": AUXILIARY_MIC_LABELS.get(mic),
            "line_count": len(mic_records),
            "security_count": len(mic_securities),
            "securities_already_in_primary": len(existing),
            "new_security_count": len(new),
            "new_security_ids": sorted(new),
        }

        print(
            f"{mic:8s} "
            f"{len(mic_records):8d} "
            f"{len(mic_securities):8d} "
            f"{len(existing):12d} "
            f"{len(new):10d}"
        )

    # ========================================================
    # TOTAL NEW SECURITIES FROM AGGREGATOR RESIDUAL
    # ========================================================

    all_only_securities = {record["isin"] for record in all_only_records}

    genuinely_new_raw = all_only_securities - primary_raw_securities

    all_common_only_securities = {record["isin"] for record in all_common_only_records}

    genuinely_new_common = all_common_only_securities - primary_common_securities

    expanded_raw_security_union = primary_raw_securities | all_raw_securities

    expanded_common_security_union = primary_common_securities | all_common_securities

    print()
    print("=" * 100)
    print("SECURITY-LEVEL UNION")
    print("=" * 100)

    print(
        "PRIMARY RAW SECURITIES:",
        len(primary_raw_securities),
    )

    print(
        "AGGREGATOR-RESIDUAL UNIQUE SECURITIES:",
        len(all_only_securities),
    )

    print(
        "GENUINELY NEW RAW SECURITIES:",
        len(genuinely_new_raw),
    )

    print(
        "EXPANDED RAW SECURITY UNION:",
        len(expanded_raw_security_union),
    )

    print()
    print(
        "PRIMARY COMMON-STOCK SECURITIES:",
        len(primary_common_securities),
    )

    print(
        "GENUINELY NEW COMMON-STOCK SECURITIES:",
        len(genuinely_new_common),
    )

    print(
        "EXPANDED COMMON-STOCK SECURITY UNION:",
        len(expanded_common_security_union),
    )

    # ========================================================
    # PRIMARY-ONLY / XACD OMISSION
    # ========================================================

    print()
    print("=" * 100)
    print("PRIMARY LINES OMITTED BY ALL-EQUITIES AGGREGATOR")
    print("=" * 100)

    omitted_mics: set[str] = set()

    for line_id in sorted(primary_only_ids):
        record = primary_raw_lines[line_id]

        mic = record["reference_mic"]

        omitted_mics.add(mic)

        print(f"{line_id} | {record['company_name']} | {record['ticker']} | {mic}")

    all_endpoint_mics = set(data["families"][AGGREGATOR]["endpoint_mics"])

    omission_explained = bool(primary_only_ids) and omitted_mics.isdisjoint(all_endpoint_mics)

    # ========================================================
    # HARD GATES — REPAIRED SEMANTICS
    # ========================================================

    hard_gates = {
        "primary_families_line_disjoint": int(data["cross_family_overlap_count"]) == 0,
        "all_only_mics_are_auxiliary": set(by_mic)
        == {
            "ETLX",
            "MTAH",
            "XPMC",
        },
        "all_only_identity_conflicts_zero": not data["all_equities_shard_diagnostics"]["raw"][
            "conflicting_identity_ids"
        ],
        "common_all_only_identity_conflicts_zero": not data["all_equities_shard_diagnostics"][
            "common"
        ]["conflicting_identity_ids"],
        "primary_only_omission_explained_by_missing_mic": omission_explained,
        "primary_only_mic_is_xacd": omitted_mics == {"XACD"},
        "primary_only_count_is_two": len(primary_only_ids) == 2,
        "primary_common_only_count_is_two": len(primary_common_only_ids) == 2,
    }

    print()
    print("=" * 100)
    print("REPAIRED HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:60s}",
            ("PASS" if passed else "FAIL"),
        )

    failed = [name for name, passed in hard_gates.items() if not passed]

    result = {
        "source": str(SOURCE),
        "interpretation": {
            "all_equities_is_authoritative_superset": False,
            "all_equities_role": "auxiliary aggregate / residual venue discovery",
            "primary_family_role": "explicit market-family taxonomy",
        },
        "counts": {
            "primary_raw_lines": len(primary_raw_ids),
            "all_equities_raw_lines": len(all_raw_ids),
            "all_equities_only_lines": len(all_only_ids),
            "primary_only_lines": len(primary_only_ids),
            "primary_raw_securities": len(primary_raw_securities),
            "all_equities_raw_securities": len(all_raw_securities),
            "genuinely_new_raw_securities": len(genuinely_new_raw),
            "expanded_raw_security_union": len(expanded_raw_security_union),
            "primary_common_securities": len(primary_common_securities),
            "genuinely_new_common_securities": len(genuinely_new_common),
            "expanded_common_security_union": len(expanded_common_security_union),
        },
        "auxiliary_mic_audit": mic_audit,
        "primary_only_ids": sorted(primary_only_ids),
        "primary_only_mics": sorted(omitted_mics),
        "all_equities_endpoint_mics": sorted(all_endpoint_mics),
        "genuinely_new_raw_security_ids": sorted(genuinely_new_raw),
        "genuinely_new_common_security_ids": sorted(genuinely_new_common),
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
