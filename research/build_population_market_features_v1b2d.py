from __future__ import annotations

import argparse
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
from euronext_pde.providers.historical_market_data import (
    RoutingHistoricalMarketDataProvider,
)

SNAPSHOT_DATE = "2026-09-13"
EXPECTED_POPULATION = 971

BASE = Path("data") / "snapshots" / SNAPSHOT_DATE / "canonical"

TRADING_LINES_PATH = BASE / "trading_lines.parquet"

CLASSIFICATION_PATH = BASE / "instrument_classification.parquet"

FEATURE_CODE_PATH = Path("src") / "euronext_pde" / "features" / "market.py"

PROVIDER_CODE_PATH = Path("src") / "euronext_pde" / "providers" / "historical_market_data.py"

SCHEMA_CODE_PATH = Path("src") / "euronext_pde" / "market_data.py"

CHECKPOINT_PATH = Path("research") / "v1b2d_population_checkpoint.jsonl"

OUTPUT_PATH = Path("research") / "v1b2d_population_market_features.tsv"

FAILURES_PATH = Path("research") / "v1b2d_population_failures.tsv"

MANIFEST_PATH = Path("research") / "v1b2d_population_manifest.json"

MAX_ATTEMPTS = 3
INTER_LINE_SLEEP_SECONDS = 0.20


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


def contract_hashes() -> dict[
    str,
    str,
]:
    paths = {
        "trading_lines": TRADING_LINES_PATH,
        "instrument_classification": CLASSIFICATION_PATH,
        "feature_code": FEATURE_CODE_PATH,
        "provider_code": PROVIDER_CODE_PATH,
        "market_data_schema": SCHEMA_CODE_PATH,
    }

    return {name: sha256_file(path) for name, path in paths.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Build the V1B2D regulated Common Stock market-feature snapshot.")
    )

    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help=("Retry lines whose latest checkpoint status is a failure."),
    )

    parser.add_argument(
        "--max-new",
        type=int,
        default=None,
        help=("Process at most N new/retried lines. Useful for controlled smoke/resume runs."),
    )

    return parser.parse_args()


def load_population() -> pd.DataFrame:
    trading = pd.read_parquet(TRADING_LINES_PATH)

    classification = pd.read_parquet(CLASSIFICATION_PATH)

    common = classification[classification["is_common_stock"]].copy()

    if len(common) != EXPECTED_POPULATION:
        raise RuntimeError(
            f"Unexpected Common Stock count: {len(common)} != {EXPECTED_POPULATION}."
        )

    if common["trading_line_id"].duplicated().any():
        raise RuntimeError("Duplicate classification trading_line_id.")

    if trading["trading_line_id"].duplicated().any():
        raise RuntimeError("Duplicate canonical trading_line_id.")

    population = common[
        [
            "snapshot_date",
            "trading_line_id",
            "security_id",
            "ticker",
            "reference_mic",
            "classification_observed_date",
            "official_issue_type",
            "official_issue_type_code",
        ]
    ].merge(
        trading[
            [
                "trading_line_id",
                "security_id",
                "ticker",
                "display_name",
                "reference_mic",
                "reference_market",
                "product_url",
                "active",
                "first_seen",
                "last_seen",
            ]
        ],
        on="trading_line_id",
        how="left",
        validate="one_to_one",
        suffixes=(
            "_classification",
            "_trading",
        ),
    )

    if len(population) != EXPECTED_POPULATION:
        raise RuntimeError("Population merge changed row count.")

    required = (
        (
            "security_id_classification",
            "security_id_trading",
        ),
        (
            "ticker_classification",
            "ticker_trading",
        ),
        (
            "reference_mic_classification",
            "reference_mic_trading",
        ),
    )

    for left, right in required:
        mismatch = population[left].astype(str) != population[right].astype(str)

        if mismatch.any():
            raise RuntimeError(f"Canonical/classification identity mismatch: {left} vs {right}.")

    population = (
        population.assign(
            security_id=(population["security_id_trading"]),
            ticker=(population["ticker_trading"]),
            reference_mic=(population["reference_mic_trading"]),
        )
        .drop(
            columns=[
                "security_id_classification",
                "security_id_trading",
                "ticker_classification",
                "ticker_trading",
                "reference_mic_classification",
                "reference_mic_trading",
            ]
        )
        .sort_values(
            [
                "reference_mic",
                "trading_line_id",
            ]
        )
        .reset_index(drop=True)
    )

    if population["trading_line_id"].duplicated().any():
        raise RuntimeError("Population contains duplicate lines.")

    return population


def read_checkpoint() -> list[dict[str, Any]]:
    if not CHECKPOINT_PATH.exists():
        return []

    lines = CHECKPOINT_PATH.read_text(
        encoding="utf-8",
    ).splitlines()

    records: list[dict[str, Any]] = []

    for index, line in enumerate(
        lines,
        start=1,
    ):
        if not line.strip():
            continue

        try:
            record = json.loads(line)

        except json.JSONDecodeError:
            if index == len(lines):
                print("WARNING: ignoring truncated final checkpoint line.")

                break

            raise RuntimeError(f"Malformed non-final checkpoint record at line {index}.") from None

        if not isinstance(
            record,
            dict,
        ):
            raise TypeError("Checkpoint record must be a dict.")

        records.append(record)

    return records


def latest_checkpoint_records(
    records: list[dict[str, Any]],
) -> dict[
    str,
    dict[str, Any],
]:
    latest: dict[
        str,
        dict[str, Any],
    ] = {}

    for record in records:
        line_id = str(record["trading_line_id"])

        latest[line_id] = record

    return latest


def append_checkpoint(
    record: dict[str, Any],
) -> None:
    CHECKPOINT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = json.dumps(
        record,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )

    with CHECKPOINT_PATH.open(
        "a",
        encoding="utf-8",
        newline="\n",
    ) as handle:
        handle.write(payload + "\n")

        handle.flush()


def make_manifest(
    *,
    hashes: dict[str, str],
    population: pd.DataFrame,
    started_at: str,
) -> dict[str, Any]:
    mic_counts = population["reference_mic"].value_counts().sort_index().to_dict()

    observed_dates = sorted(
        str(value) for value in population["classification_observed_date"].dropna().unique()
    )

    return {
        "milestone": "V1B2D",
        "snapshot_date": SNAPSHOT_DATE,
        "population_definition": (
            "Euronext Regulated trading lines with official is_common_stock=True"
        ),
        "expected_population": EXPECTED_POPULATION,
        "population_count": len(population),
        "classification_observed_dates": observed_dates,
        "mic_counts": {str(key): int(value) for key, value in mic_counts.items()},
        "contract_hashes": hashes,
        "started_at_utc": started_at,
        "last_updated_at_utc": started_at,
        "checkpoint_path": str(CHECKPOINT_PATH),
        "output_path": str(OUTPUT_PATH),
        "failures_path": str(FAILURES_PATH),
        "secrets_persisted": False,
    }


def initialize_or_validate_manifest(
    *,
    hashes: dict[str, str],
    population: pd.DataFrame,
) -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        manifest = make_manifest(
            hashes=hashes,
            population=population,
            started_at=utc_now(),
        )

        MANIFEST_PATH.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return manifest

    manifest = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(
        manifest,
        dict,
    ):
        raise TypeError("Existing manifest is invalid.")

    existing_hashes = manifest.get("contract_hashes")

    if existing_hashes != hashes:
        raise RuntimeError(
            "V1B2D contract changed since the "
            "checkpoint was created. Refusing to "
            "mix rows generated by different "
            "inputs/provider/feature code."
        )

    if int(
        manifest.get(
            "population_count",
            -1,
        )
    ) != len(population):
        raise RuntimeError("Population count changed since checkpoint creation.")

    return manifest


def base_record(
    row: Any,
) -> dict[str, Any]:
    return {
        "snapshot_date": str(row.snapshot_date),
        "classification_observed_date": str(row.classification_observed_date),
        "trading_line_id": str(row.trading_line_id),
        "security_id": str(row.security_id),
        "ticker": str(row.ticker),
        "display_name": str(row.display_name),
        "reference_mic": str(row.reference_mic),
        "reference_market": str(row.reference_market),
        "active": bool(row.active),
        "official_issue_type": str(row.official_issue_type),
        "official_issue_type_code": str(row.official_issue_type_code),
    }


def failure_record(
    *,
    row: Any,
    status: str,
    stage: str,
    exc: Exception,
    attempts: int,
) -> dict[str, Any]:
    record = base_record(row)

    record.update(
        {
            "status": status,
            "failure_stage": stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "attempts": attempts,
            "completed_at_utc": utc_now(),
        }
    )

    return record


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
                    str(exc)[:160],
                )

                time.sleep(delay)

    if last_error is None:
        raise RuntimeError("Retry loop ended without result or captured error.")

    raise last_error


def success_record(
    *,
    row: Any,
    observations: list[Any],
    attempts: int,
) -> dict[str, Any]:
    features = compute_market_risk_features(observations)

    latest = observations[-1]
    earliest = observations[0]

    record = base_record(row)

    record.update(
        {
            "status": "PASS",
            "failure_stage": "",
            "error_type": "",
            "error_message": "",
            "attempts": attempts,
            "provider": features.provider,
            "provider_mic": features.provider_mic,
            "adjustment_basis": features.adjustment_basis.value,
            "first_session_date": earliest.session_date.isoformat(),
            "as_of_date": features.as_of_date.isoformat(),
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
    )

    return record


def materialize_outputs(
    *,
    population: pd.DataFrame,
    latest: dict[
        str,
        dict[str, Any],
    ],
) -> pd.DataFrame:
    population_ids = list(population["trading_line_id"].astype(str))

    ordered_records = [latest[line_id] for line_id in population_ids if line_id in latest]

    frame = pd.DataFrame(ordered_records)

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame.to_csv(
        OUTPUT_PATH,
        sep="\t",
        index=False,
    )

    if frame.empty:
        failures = frame.copy()

    else:
        failures = frame[frame["status"] != "PASS"].copy()

    failures.to_csv(
        FAILURES_PATH,
        sep="\t",
        index=False,
    )

    return frame


def print_summary(
    *,
    population: pd.DataFrame,
    result: pd.DataFrame,
) -> None:
    print()
    print("=" * 100)
    print("V1B2D — POPULATION SNAPSHOT SUMMARY")
    print("=" * 100)

    print(
        "POPULATION:",
        len(population),
    )

    print(
        "CHECKPOINTED:",
        len(result),
        "/",
        len(population),
    )

    if result.empty:
        return

    status_counts = result["status"].value_counts().to_dict()

    for status, count in sorted(status_counts.items()):
        print(
            f"{status:20s}",
            count,
        )

    passed = result[result["status"] == "PASS"]

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
        if column not in passed.columns:
            continue

        count = int(passed[column].fillna(False).astype(bool).sum())

        print(
            f"{column:30s}",
            f"{count}/{len(passed)}",
        )

    print()
    print("BY MIC")

    for mic in sorted(population["reference_mic"].unique()):
        expected = int((population["reference_mic"] == mic).sum())

        part = result[result["reference_mic"] == mic]

        good = part[part["status"] == "PASS"]

        print(
            f"{mic:6s}",
            f"checkpointed={len(part)}/{expected}",
            f"pass={len(good)}/{expected}",
        )


def update_manifest(
    *,
    manifest: dict[str, Any],
    result: pd.DataFrame,
    population: pd.DataFrame,
) -> None:
    manifest["last_updated_at_utc"] = utc_now()

    manifest["checkpointed_count"] = len(result)

    manifest["complete"] = len(result) == len(population)

    if result.empty:
        manifest["status_counts"] = {}

    else:
        manifest["status_counts"] = {
            str(key): int(value) for key, value in result["status"].value_counts().items()
        }

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    population = load_population()

    hashes = contract_hashes()

    manifest = initialize_or_validate_manifest(
        hashes=hashes,
        population=population,
    )

    checkpoint_records = read_checkpoint()

    latest = latest_checkpoint_records(checkpoint_records)

    population_ids = set(population["trading_line_id"].astype(str))

    unknown_checkpoint_ids = set(latest) - population_ids

    if unknown_checkpoint_ids:
        raise RuntimeError("Checkpoint contains lines outside the frozen population.")

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

    print("=" * 100)
    print("V1B2D — REGULATED COMMON-STOCK POPULATION MARKET FEATURES")
    print("=" * 100)

    print(
        "POPULATION:",
        len(population),
    )

    print(
        "EXISTING CHECKPOINT LINES:",
        len(latest),
    )

    print(
        "RETRY FAILURES:",
        args.retry_failures,
    )

    processed_this_run = 0

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        provider = RoutingHistoricalMarketDataProvider(client)

        for position, row in enumerate(
            population.itertuples(index=False),
            start=1,
        ):
            line_id = str(row.trading_line_id)

            previous = latest.get(line_id)

            if previous is not None:
                previous_status = str(
                    previous.get(
                        "status",
                        "",
                    )
                )

                if previous_status == "PASS":
                    continue

                if not args.retry_failures:
                    continue

            if args.max_new is not None and processed_this_run >= args.max_new:
                break

            print()
            print(
                f"[{position:03d}/"
                f"{len(population)}] "
                f"{row.reference_mic} "
                f"{line_id} | "
                f"{row.display_name}"
            )

            try:
                observations, attempts = fetch_with_retry(
                    provider,
                    trading_line_id=(line_id),
                    security_id=str(row.security_id),
                    reference_mic=str(row.reference_mic),
                )

            except (
                httpx.HTTPError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                record = failure_record(
                    row=row,
                    status="FETCH_FAIL",
                    stage="fetch",
                    exc=exc,
                    attempts=MAX_ATTEMPTS,
                )

                print(
                    "  FETCH_FAIL:",
                    type(exc).__name__,
                    str(exc)[:240],
                )

            else:
                try:
                    record = success_record(
                        row=row,
                        observations=observations,
                        attempts=attempts,
                    )

                except (
                    RuntimeError,
                    TypeError,
                    ValueError,
                ) as exc:
                    record = failure_record(
                        row=row,
                        status="FEATURE_FAIL",
                        stage="feature",
                        exc=exc,
                        attempts=attempts,
                    )

                    print(
                        "  FEATURE_FAIL:",
                        type(exc).__name__,
                        str(exc)[:240],
                    )

                else:
                    print(
                        "  PASS | sessions=",
                        record["available_sessions"],
                        " | as_of=",
                        record["as_of_date"],
                        " | 6m=",
                        record["has_6m"],
                        " | dd252=",
                        record["has_drawdown_252d"],
                        sep="",
                    )

            append_checkpoint(record)

            latest[line_id] = record

            processed_this_run += 1

            if processed_this_run % 25 == 0:
                partial = materialize_outputs(
                    population=population,
                    latest=latest,
                )

                update_manifest(
                    manifest=manifest,
                    result=partial,
                    population=population,
                )

                print(
                    "  CHECKPOINT MATERIALIZED:",
                    len(partial),
                )

            time.sleep(INTER_LINE_SLEEP_SECONDS)

    result = materialize_outputs(
        population=population,
        latest=latest,
    )

    update_manifest(
        manifest=manifest,
        result=result,
        population=population,
    )

    print_summary(
        population=population,
        result=result,
    )

    print()
    print(
        "WROTE:",
        OUTPUT_PATH,
    )

    print(
        "FAILURES:",
        FAILURES_PATH,
    )

    print(
        "CHECKPOINT:",
        CHECKPOINT_PATH,
    )

    print(
        "MANIFEST:",
        MANIFEST_PATH,
    )

    if len(result) < len(population):
        print()
        print("STATUS: PARTIAL — rerun the same command to resume.")

    else:
        failures = int((result["status"] != "PASS").sum())

        if failures:
            print()
            print("STATUS: COMPLETE_WITH_FAILURES")

            print("Retry only failed lines with:")

            print(
                "uv run python research/build_population_market_features_v1b2d.py --retry-failures"
            )

        else:
            print()
            print("STATUS: COMPLETE_PASS")


if __name__ == "__main__":
    main()
