from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from euronext_pde.features.market import (
    compute_market_risk_features,
)
from euronext_pde.market_data import (
    AdjustmentBasis,
)
from euronext_pde.providers.historical_market_data import (
    EURONEXT_PROVIDER,
    NoHistoryError,
    RoutingHistoricalMarketDataProvider,
)

PARENT_OUTPUT = Path("research") / "v1b2d_population_market_features.tsv"

PARENT_FAILURES = Path("research") / "v1b2d_population_failures.tsv"

PARENT_MANIFEST = Path("research") / "v1b2d_population_manifest.json"

RAW_AUDIT = Path("research") / "v1b2d_r0_failure_raw_audit.json"

OUTPUT = Path("research") / "v1b2d_r1_population_market_features.tsv"

NONPASS_OUTPUT = Path("research") / "v1b2d_r1_population_nonpass.tsv"

REPAIR_EVIDENCE = Path("research") / "v1b2d_r1_repair_evidence.tsv"

MANIFEST = Path("research") / "v1b2d_r1_manifest.json"

MARKET_SCHEMA = Path("src") / "euronext_pde" / "market_data.py"

PROVIDER_CODE = Path("src") / "euronext_pde" / "providers" / "historical_market_data.py"

FEATURE_CODE = Path("src") / "euronext_pde" / "features" / "market.py"

REPAIR_IDS = {
    "IT0005481855-MTAA": "MET.EXTRA GROUP",
    "IT0005730095-MTAA": "EPH INVEST",
    "BMG455841020-XAMS": "HAL TRUST",
}

EXPECTED_PARENT_STATUS = {
    "PASS": 968,
    "FETCH_FAIL": 2,
    "FEATURE_FAIL": 1,
}

EXPECTED_REPAIR_PARENT_STATUS = {
    "IT0005481855-MTAA": "FETCH_FAIL",
    "IT0005730095-MTAA": "FETCH_FAIL",
    "BMG455841020-XAMS": "FEATURE_FAIL",
}

MAX_ATTEMPTS = 3


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def json_safe(
    value: Any,
) -> Any:
    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    if hasattr(
        value,
        "item",
    ):
        try:
            return value.item()

        except (
            TypeError,
            ValueError,
        ):
            pass

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    return str(value)


def semantic_hash(
    frame: pd.DataFrame,
) -> str:
    ordered = frame.sort_values("trading_line_id").reset_index(drop=True)

    records: list[dict[str, Any]] = []

    for row in ordered.to_dict(orient="records"):
        records.append({str(key): json_safe(value) for key, value in row.items()})

    payload = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def status_counts(
    frame: pd.DataFrame,
) -> dict[
    str,
    int,
]:
    return {str(key): int(value) for key, value in frame["status"].value_counts().items()}


def check_parent(
    parent: pd.DataFrame,
) -> None:
    if len(parent) != 971:
        raise RuntimeError("Parent output must contain 971 rows.")

    if parent["trading_line_id"].duplicated().any():
        raise RuntimeError("Parent output contains duplicate trading lines.")

    actual = status_counts(parent)

    if actual != EXPECTED_PARENT_STATUS:
        raise RuntimeError(f"Unexpected parent status counts: {actual}")

    indexed = parent.set_index(
        "trading_line_id",
        drop=False,
    )

    for line_id, expected_status in EXPECTED_REPAIR_PARENT_STATUS.items():
        if line_id not in indexed.index:
            raise RuntimeError(f"Repair line missing from parent: {line_id}")

        actual_status = str(
            indexed.loc[
                line_id,
                "status",
            ]
        )

        if actual_status != expected_status:
            raise RuntimeError(
                f"{line_id}: expected parent {expected_status}, got {actual_status}."
            )


def fetch_with_retry(
    provider: RoutingHistoricalMarketDataProvider,
    *,
    trading_line_id: str,
    security_id: str,
    reference_mic: str,
) -> tuple[
    list[Any],
    int,
]:
    last_error: Exception | None = None

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1,
    ):
        try:
            observations = provider.fetch(
                trading_line_id=(trading_line_id),
                security_id=(security_id),
                reference_mic=(reference_mic),
            )

            return (
                observations,
                attempt,
            )

        except NoHistoryError:
            raise

        except (
            httpx.HTTPError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            last_error = exc

            if attempt < MAX_ATTEMPTS:
                delay = float(2 ** (attempt - 1))

                print(
                    "    retry",
                    attempt + 1,
                    "after",
                    f"{delay:.0f}s",
                    "|",
                    type(exc).__name__,
                    str(exc)[:180],
                )

                time.sleep(delay)

    if last_error is None:
        raise RuntimeError("Retry loop ended without result.")

    raise last_error


def success_updates(
    observations: list[Any],
    *,
    attempts: int,
) -> dict[
    str,
    Any,
]:
    if not observations:
        raise RuntimeError("Successful repair received zero observations.")

    features = compute_market_risk_features(observations)

    earliest = observations[0]
    latest = observations[-1]

    return {
        "status": "PASS",
        "failure_stage": "",
        "error_type": "",
        "error_message": "",
        "attempts": attempts,
        "provider": features.provider,
        "provider_mic": features.provider_mic,
        "adjustment_basis": (features.adjustment_basis.value),
        "first_session_date": (earliest.session_date.isoformat()),
        "as_of_date": (features.as_of_date.isoformat()),
        "available_sessions": features.available_sessions,
        "latest_close": latest.close,
        "latest_vwap": latest.vwap,
        "latest_shares": latest.number_of_shares,
        "latest_trades": latest.number_of_trades,
        "latest_turnover": latest.turnover,
        "momentum_1m": features.momentum_1m,
        "momentum_3m": features.momentum_3m,
        "momentum_6m": features.momentum_6m,
        "volatility_60d_annualized": (features.volatility_60d_annualized),
        "current_drawdown_252d": (features.current_drawdown_252d),
        "max_drawdown_252d": (features.max_drawdown_252d),
        "median_shares_20d": (features.median_shares_20d),
        "median_trades_20d": (features.median_trades_20d),
        "median_turnover_20d": (features.median_turnover_20d),
        "median_vwap_20d": (features.median_vwap_20d),
        "has_1m": features.has_1m,
        "has_3m": features.has_3m,
        "has_6m": features.has_6m,
        "has_volatility_60d": (features.has_volatility_60d),
        "has_drawdown_252d": (features.has_drawdown_252d),
        "has_liquidity_20d": (features.has_liquidity_20d),
        "completed_at_utc": utc_now(),
    }


def no_history_updates(
    *,
    attempts: int,
    message: str,
) -> dict[
    str,
    Any,
]:
    return {
        "status": "NO_HISTORY",
        "failure_stage": "provider_history",
        "error_type": "NoHistoryError",
        "error_message": message,
        "attempts": attempts,
        "provider": EURONEXT_PROVIDER,
        "provider_mic": "XAMS",
        "adjustment_basis": (AdjustmentBasis.PROVIDER_DEFAULT.value),
        "first_session_date": None,
        "as_of_date": None,
        "available_sessions": 0,
        "latest_close": None,
        "latest_vwap": None,
        "latest_shares": None,
        "latest_trades": None,
        "latest_turnover": None,
        "momentum_1m": None,
        "momentum_3m": None,
        "momentum_6m": None,
        "volatility_60d_annualized": None,
        "current_drawdown_252d": None,
        "max_drawdown_252d": None,
        "median_shares_20d": None,
        "median_trades_20d": None,
        "median_turnover_20d": None,
        "median_vwap_20d": None,
        "has_1m": False,
        "has_3m": False,
        "has_6m": False,
        "has_volatility_60d": False,
        "has_drawdown_252d": False,
        "has_liquidity_20d": False,
        "completed_at_utc": utc_now(),
    }


def main() -> None:
    required_files = (
        PARENT_OUTPUT,
        PARENT_FAILURES,
        PARENT_MANIFEST,
        RAW_AUDIT,
        MARKET_SCHEMA,
        PROVIDER_CODE,
        FEATURE_CODE,
    )

    for path in required_files:
        if not path.exists():
            raise FileNotFoundError(path)

    parent_output_sha_before = sha256_file(PARENT_OUTPUT)

    parent = pd.read_csv(
        PARENT_OUTPUT,
        sep="\t",
    )

    check_parent(parent)

    parent_pass = parent[parent["status"] == "PASS"].copy()

    if len(parent_pass) != 968:
        raise RuntimeError("Expected exactly 968 frozen parent PASS rows.")

    parent_pass_ids = set(parent_pass["trading_line_id"].astype(str))

    frozen_pass_hash_before = semantic_hash(parent_pass)

    repaired = parent.copy(deep=True)

    indexed_parent = parent.set_index(
        "trading_line_id",
        drop=False,
    )

    evidence: list[dict[str, Any]] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        provider = RoutingHistoricalMarketDataProvider(client)

        for line_id, expected_name in REPAIR_IDS.items():
            old = indexed_parent.loc[line_id]

            security_id = str(old["security_id"])

            reference_mic = str(old["reference_mic"])

            display_name = str(old["display_name"])

            if display_name != expected_name:
                raise RuntimeError(f"Unexpected display name for {line_id}: {display_name!r}")

            print()
            print("=" * 100)
            print(
                line_id,
                "|",
                display_name,
            )
            print("=" * 100)

            try:
                observations, attempts = fetch_with_retry(
                    provider,
                    trading_line_id=(line_id),
                    security_id=(security_id),
                    reference_mic=(reference_mic),
                )

            except NoHistoryError as exc:
                if line_id != "BMG455841020-XAMS":
                    raise RuntimeError(f"Unexpected NO_HISTORY for {line_id}.") from exc

                updates = no_history_updates(
                    attempts=1,
                    message=str(exc),
                )

                print("RESULT: NO_HISTORY")

                evidence.append(
                    {
                        "trading_line_id": line_id,
                        "display_name": display_name,
                        "parent_status": str(old["status"]),
                        "repair_status": "NO_HISTORY",
                        "available_sessions": 0,
                        "as_of_date": None,
                        "has_6m": False,
                        "has_drawdown_252d": False,
                        "note": (
                            "Official Euronext "
                            "endpoint returned "
                            "HTTP 200 with zero "
                            "historical rows."
                        ),
                    }
                )

            else:
                if line_id == "BMG455841020-XAMS":
                    raise RuntimeError("HAL TRUST unexpectedly returned history during R1.")

                updates = success_updates(
                    observations,
                    attempts=attempts,
                )

                print("RESULT: PASS")

                print(
                    "SESSIONS:",
                    updates["available_sessions"],
                )

                print(
                    "AS OF:",
                    updates["as_of_date"],
                )

                print(
                    "6M:",
                    updates["has_6m"],
                )

                print(
                    "DD252:",
                    updates["has_drawdown_252d"],
                )

                print(
                    "LIQ20:",
                    updates["has_liquidity_20d"],
                )

                evidence.append(
                    {
                        "trading_line_id": line_id,
                        "display_name": display_name,
                        "parent_status": str(old["status"]),
                        "repair_status": "PASS",
                        "available_sessions": updates["available_sessions"],
                        "as_of_date": updates["as_of_date"],
                        "has_6m": updates["has_6m"],
                        "has_drawdown_252d": updates["has_drawdown_252d"],
                        "note": (
                            "Nullable ancillary source fields accepted; close remained mandatory."
                        ),
                    }
                )

            mask = repaired["trading_line_id"].astype(str) == line_id

            if int(mask.sum()) != 1:
                raise RuntimeError(f"Expected one output row for {line_id}.")

            for column, value in updates.items():
                if column not in repaired.columns:
                    raise RuntimeError(f"Repair tried to introduce unexpected column: {column}")

                repaired.loc[
                    mask,
                    column,
                ] = value

    # ========================================================
    # Prove the 968 old PASS rows were not changed.
    # ========================================================

    frozen_after = repaired[repaired["trading_line_id"].astype(str).isin(parent_pass_ids)].copy()

    frozen_pass_hash_after = semantic_hash(frozen_after)

    frozen_pass_unchanged = frozen_pass_hash_before == frozen_pass_hash_after

    # ========================================================
    # Final hard gates
    # ========================================================

    final_counts = status_counts(repaired)

    expected_final_counts = {
        "PASS": 970,
        "NO_HISTORY": 1,
    }

    indexed_final = repaired.set_index(
        "trading_line_id",
        drop=False,
    )

    hard_gates = {
        "population_971": len(repaired) == 971,
        "no_duplicate_lines": not repaired["trading_line_id"].duplicated().any(),
        "parent_pass_rows_968": len(parent_pass) == 968,
        "parent_pass_rows_unchanged": frozen_pass_unchanged,
        "met_extra_repaired_pass": (
            indexed_final.loc[
                "IT0005481855-MTAA",
                "status",
            ]
            == "PASS"
        ),
        "eph_invest_repaired_pass": (
            indexed_final.loc[
                "IT0005730095-MTAA",
                "status",
            ]
            == "PASS"
        ),
        "hal_classified_no_history": (
            indexed_final.loc[
                "BMG455841020-XAMS",
                "status",
            ]
            == "NO_HISTORY"
        ),
        "final_status_counts_exact": final_counts == expected_final_counts,
        "no_fetch_fail": "FETCH_FAIL" not in final_counts,
        "no_parse_fail": "PARSE_FAIL" not in final_counts,
        "no_feature_fail": "FEATURE_FAIL" not in final_counts,
    }

    print()
    print("=" * 100)
    print("V1B2D-R1 — REPAIR EXECUTION SUMMARY")
    print("=" * 100)

    print(
        "POPULATION:",
        len(repaired),
    )

    for status, count in sorted(final_counts.items()):
        print(
            f"{status:20s}",
            count,
        )

    passed = repaired[repaired["status"] == "PASS"]

    print()
    print("FEATURE COVERAGE AMONG PASS")

    for column in (
        "has_1m",
        "has_3m",
        "has_6m",
        "has_volatility_60d",
        "has_drawdown_252d",
        "has_liquidity_20d",
    ):
        count = int(passed[column].fillna(False).astype(bool).sum())

        print(
            f"{column:30s}",
            f"{count}/{len(passed)}",
        )

    print()
    print("BY MIC")

    for mic in sorted(repaired["reference_mic"].astype(str).unique()):
        part = repaired[repaired["reference_mic"].astype(str) == mic]

        good = part[part["status"] == "PASS"]

        no_history = part[part["status"] == "NO_HISTORY"]

        print(
            f"{mic:6s}",
            f"pass={len(good)}/{len(part)}",
            f"no_history={len(no_history)}",
        )

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed_gate in hard_gates.items():
        print(
            f"{name:45s}",
            ("PASS" if passed_gate else "FAIL"),
        )

    failed_gates = [name for name, passed_gate in hard_gates.items() if not passed_gate]

    if failed_gates:
        raise RuntimeError(f"Failed gates: {failed_gates}")

    # ========================================================
    # Write only after all scientific gates pass.
    # ========================================================

    repaired.to_csv(
        OUTPUT,
        sep="\t",
        index=False,
    )

    nonpass = repaired[repaired["status"] != "PASS"].copy()

    nonpass.to_csv(
        NONPASS_OUTPUT,
        sep="\t",
        index=False,
    )

    evidence_frame = pd.DataFrame(evidence)

    evidence_frame.to_csv(
        REPAIR_EVIDENCE,
        sep="\t",
        index=False,
    )

    parent_output_sha_after = sha256_file(PARENT_OUTPUT)

    parent_artifact_unchanged = parent_output_sha_before == parent_output_sha_after

    if not parent_artifact_unchanged:
        raise RuntimeError("Parent V1B2D output changed during R1.")

    manifest = {
        "milestone": "V1B2D-R1",
        "purpose": (
            "Scientifically neutral repair of "
            "nullable ancillary market fields "
            "and explicit NO_HISTORY state."
        ),
        "population_count": len(repaired),
        "parent_status_counts": EXPECTED_PARENT_STATUS,
        "final_status_counts": final_counts,
        "repair_ids": REPAIR_IDS,
        "parent_v1b2d_reused_pass_rows": 968,
        "parent_pass_rows_recomputed": 0,
        "parent_pass_semantic_hash_before": frozen_pass_hash_before,
        "parent_pass_semantic_hash_after": frozen_pass_hash_after,
        "parent_pass_rows_unchanged": frozen_pass_unchanged,
        "parent_output_sha256": parent_output_sha_before,
        "parent_output_unchanged": parent_artifact_unchanged,
        "parent_manifest_sha256": sha256_file(PARENT_MANIFEST),
        "parent_failures_sha256": sha256_file(PARENT_FAILURES),
        "raw_failure_audit_sha256": sha256_file(RAW_AUDIT),
        "current_code_hashes": {
            "market_data_schema": sha256_file(MARKET_SCHEMA),
            "historical_market_provider": sha256_file(PROVIDER_CODE),
            "market_features": sha256_file(FEATURE_CODE),
        },
        "repair_policy": {
            "close_required": True,
            "ancillary_fields_nullable": True,
            "imputation_used": False,
            "sessions_dropped_for_missing_ancillary_fields": False,
            "no_history_is_failure": False,
            "jwt_or_cookie_values_persisted": False,
        },
        "hard_gates": hard_gates,
        "completed_at_utc": utc_now(),
        "output": str(OUTPUT),
        "nonpass_output": str(NONPASS_OUTPUT),
        "repair_evidence": str(REPAIR_EVIDENCE),
    }

    MANIFEST.write_text(
        json.dumps(
            manifest,
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

    print(
        "NONPASS:",
        NONPASS_OUTPUT,
    )

    print(
        "EVIDENCE:",
        REPAIR_EVIDENCE,
    )

    print(
        "MANIFEST:",
        MANIFEST,
    )

    print()
    print("STATUS: PASS")


if __name__ == "__main__":
    main()
