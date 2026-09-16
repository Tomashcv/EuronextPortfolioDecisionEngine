from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from euronext_pde.paths import ProjectPaths
from euronext_pde.providers.euronext_universe import (
    COMPETITION_MICS,
    ENDPOINT,
    REFERER,
    build_payload,
    parse_name_fragment,
)

COMMON_STOCK_CODE = "101"
COMMON_STOCK_LABEL = "Common Stock"

URL_MIC_RE = re.compile(r"-([A-Z0-9]{4})/?$")


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def latest_canonical_snapshot() -> Path:
    paths = ProjectPaths.discover()

    candidates = sorted(
        path
        for path in paths.snapshots.iterdir()
        if path.is_dir() and (path / "canonical" / "trading_lines.parquet").is_file()
    )

    if not candidates:
        raise RuntimeError("No canonical snapshot found.")

    return candidates[-1]


def fetch_directory(
    client: httpx.Client,
    *,
    common_stock_only: bool,
) -> dict[str, Any]:
    payload = build_payload(
        start=0,
        length=2000,
        draw=1,
    )

    if common_stock_only:
        payload["args[issueType]"] = COMMON_STOCK_CODE
        payload["args[initialLetter]"] = ""

    response = client.post(
        ENDPOINT,
        params={
            "mics": ",".join(COMPETITION_MICS),
        },
        data=payload,
        headers={
            "Referer": REFERER,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    response.raise_for_status()

    result = response.json()

    if not isinstance(
        result,
        dict,
    ):
        raise TypeError("Unexpected Euronext response.")

    return result


def directory_rows(
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


def trading_line_id_from_row(
    row: list[Any],
) -> str:
    isin = str(row[1]).strip()

    _, product_url = parse_name_fragment(str(row[0]))

    match = URL_MIC_RE.search(product_url)

    if match is None:
        raise RuntimeError(f"Could not extract reference MIC from {product_url}")

    return f"{isin}-{match.group(1)}"


def main() -> None:
    snapshot = latest_canonical_snapshot()

    canonical = snapshot / "canonical"

    trading_lines_path = canonical / "trading_lines.parquet"

    output_path = canonical / "instrument_classification.parquet"

    manifest_path = canonical / "instrument_classification_manifest.json"

    if output_path.exists():
        raise FileExistsError(f"Classification already exists: {output_path}")

    if manifest_path.exists():
        raise FileExistsError(f"Manifest already exists: {manifest_path}")

    trading_lines = pd.read_parquet(trading_lines_path)

    snapshot_ids = set(trading_lines["trading_line_id"].astype(str))

    observed_at = datetime.now(UTC)

    observed_date = observed_at.date()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
    }

    with httpx.Client(
        headers=headers,
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        raw_payload = fetch_directory(
            client,
            common_stock_only=False,
        )

        common_payload = fetch_directory(
            client,
            common_stock_only=True,
        )

    raw_rows = directory_rows(raw_payload)

    common_rows = directory_rows(common_payload)

    raw_ids = {trading_line_id_from_row(row) for row in raw_rows}

    common_ids = {trading_line_id_from_row(row) for row in common_rows}

    # --------------------------------------------------------
    # HARD BINDING GATES
    # --------------------------------------------------------

    if raw_ids != snapshot_ids:
        added = sorted(raw_ids - snapshot_ids)

        missing = sorted(snapshot_ids - raw_ids)

        raise RuntimeError(
            "Live raw directory no longer exactly "
            "matches the frozen snapshot. "
            f"added={added}, missing={missing}"
        )

    if not common_ids.issubset(raw_ids):
        raise RuntimeError("Common Stock result is not a subset of the raw directory.")

    # --------------------------------------------------------
    # LINE-LEVEL CLASSIFICATION
    # --------------------------------------------------------

    classification = trading_lines[
        [
            "as_of_date",
            "trading_line_id",
            "security_id",
            "ticker",
            "reference_mic",
        ]
    ].copy()

    classification = classification.rename(
        columns={
            "as_of_date": "snapshot_date",
        }
    )

    classification["classification_observed_date"] = observed_date

    classification["is_common_stock"] = classification["trading_line_id"].isin(common_ids)

    classification["official_issue_type"] = None

    classification["official_issue_type_code"] = None

    common_mask = classification["is_common_stock"]

    classification.loc[
        common_mask,
        "official_issue_type",
    ] = COMMON_STOCK_LABEL

    classification.loc[
        common_mask,
        "official_issue_type_code",
    ] = COMMON_STOCK_CODE

    classification["classification_source"] = "Euronext Live"

    classification["classification_source_url"] = REFERER

    classification["classification_method"] = "official_directory_filter"

    classification["classification_filter_field"] = "args[issueType]"

    classification["classification_filter_value"] = COMMON_STOCK_CODE

    classification["point_in_time_note"] = (
        "Classification observed after snapshot; "
        "live raw trading-line identity set exactly "
        "matched frozen snapshot before binding."
    )

    # --------------------------------------------------------
    # SECURITY CONSISTENCY
    # --------------------------------------------------------

    security_check = classification.groupby("security_id")["is_common_stock"].agg(
        [
            "min",
            "max",
            "count",
        ]
    )

    mixed_security_ids = security_check[
        security_check["min"] != security_check["max"]
    ].index.tolist()

    # --------------------------------------------------------
    # HARD FINAL GATES
    # --------------------------------------------------------

    gates = {
        "raw_exactly_matches_snapshot": raw_ids == snapshot_ids,
        "common_subset_of_raw": common_ids.issubset(raw_ids),
        "classification_row_count": len(classification) == len(trading_lines),
        "classification_id_unique": not classification["trading_line_id"].duplicated().any(),
        "common_line_count": int(classification["is_common_stock"].sum()) == len(common_ids),
        "expected_common_line_count": len(common_ids) == 971,
        "expected_non_common_line_count": int((~classification["is_common_stock"]).sum()) == 40,
        "no_mixed_security_classification": not mixed_security_ids,
    }

    failed = [name for name, passed in gates.items() if not passed]

    if failed:
        raise RuntimeError(f"Classification gates failed: {failed}")

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

    classification.to_parquet(
        output_path,
        index=False,
    )

    file_hash = sha256_file(output_path)

    manifest = {
        "schema_version": "v1a3c",
        "snapshot_directory": str(snapshot),
        "snapshot_date": str(classification["snapshot_date"].iloc[0]),
        "classification_observed_at_utc": observed_at.isoformat(),
        "source": "Euronext Live",
        "source_url": REFERER,
        "competition_mics": list(COMPETITION_MICS),
        "official_filter": {
            "label": COMMON_STOCK_LABEL,
            "field": "args[issueType]",
            "value": COMMON_STOCK_CODE,
        },
        "counts": {
            "trading_lines": len(classification),
            "common_stock_lines": int(classification["is_common_stock"].sum()),
            "non_common_stock_lines": int((~classification["is_common_stock"]).sum()),
            "securities": int(classification["security_id"].nunique()),
            "common_stock_securities": int(
                classification.loc[
                    classification["is_common_stock"],
                    "security_id",
                ].nunique()
            ),
            "mixed_securities": len(mixed_security_ids),
        },
        "point_in_time": {
            "classification_observed_on_snapshot_date": False,
            "raw_identity_set_exact_match": True,
            "note": (
                "Classification was observed after the "
                "snapshot date. The live raw trading-line "
                "identity set was required to exactly match "
                "the frozen snapshot before binding."
            ),
        },
        "hard_gates": gates,
        "artifacts": {
            "instrument_classification.parquet": {
                "sha256": file_hash,
            },
        },
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 100)
    print("V1A3C — CANONICAL INSTRUMENT CLASSIFICATION")
    print("=" * 100)

    print()
    print(
        "SNAPSHOT:",
        snapshot,
    )

    print(
        "CLASSIFICATION OBSERVED:",
        observed_at.isoformat(),
    )

    print()
    print(
        "TRADING LINES:",
        len(classification),
    )

    print(
        "COMMON STOCK LINES:",
        int(classification["is_common_stock"].sum()),
    )

    print(
        "NON-COMMON STOCK LINES:",
        int((~classification["is_common_stock"]).sum()),
    )

    print(
        "SECURITIES:",
        classification["security_id"].nunique(),
    )

    print(
        "COMMON STOCK SECURITIES:",
        classification.loc[
            classification["is_common_stock"],
            "security_id",
        ].nunique(),
    )

    print(
        "MIXED SECURITIES:",
        len(mixed_security_ids),
    )

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in gates.items():
        print(
            f"{name:45s}",
            "PASS" if passed else "FAIL",
        )

    print()
    print(
        "WROTE:",
        output_path,
    )

    print(
        "SHA256:",
        file_hash,
    )

    print(
        "MANIFEST:",
        manifest_path,
    )

    print()
    print("STATUS: PASS")


if __name__ == "__main__":
    main()
