from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

OBSERVED_DATE = date(
    2026,
    9,
    14,
)

SOURCE = Path("research") / "v1b2d_r1_population_market_features.tsv"

SOURCE_MANIFEST = Path("research") / "v1b2d_r1_manifest.json"

SUMMARY_OUTPUT = Path("research") / "v1b2e_distribution_summary.tsv"

QUALITY_OUTPUT = Path("research") / "v1b2e_quality_flags.tsv"

TAILS_OUTPUT = Path("research") / "v1b2e_tail_observations.tsv"

MANIFEST_OUTPUT = Path("research") / "v1b2e_manifest.json"

EXPECTED_MICS = (
    "MTAA",
    "XAMS",
    "XBRU",
    "XLIS",
    "XMSM",
    "XOSL",
    "XPAR",
)

EXPECTED_STATUS_COUNTS = {
    "PASS": 970,
    "NO_HISTORY": 1,
}

FEATURE_RULES = {
    "has_1m": 22,
    "has_3m": 64,
    "has_6m": 127,
    "has_volatility_60d": 61,
    "has_drawdown_252d": 252,
}

FEATURE_VALUE_MAP = {
    "has_1m": ("momentum_1m",),
    "has_3m": ("momentum_3m",),
    "has_6m": ("momentum_6m",),
    "has_volatility_60d": ("volatility_60d_annualized",),
    "has_drawdown_252d": (
        "current_drawdown_252d",
        "max_drawdown_252d",
    ),
}

GLOBAL_METRICS = (
    "available_sessions",
    "momentum_1m",
    "momentum_3m",
    "momentum_6m",
    "volatility_60d_annualized",
    "current_drawdown_252d",
    "max_drawdown_252d",
)

MIC_DIAGNOSTIC_METRICS = (
    "median_shares_20d",
    "median_trades_20d",
    "median_turnover_20d",
    "median_vwap_20d",
)

QUANTILES = (
    0.00,
    0.01,
    0.05,
    0.10,
    0.25,
    0.50,
    0.75,
    0.90,
    0.95,
    0.99,
    1.00,
)


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


def as_bool_series(
    series: pd.Series,
) -> pd.Series:
    if series.dtype == bool:
        return series

    mapping = {
        "true": True,
        "false": False,
    }

    normalized = series.astype(str).str.strip().str.lower().map(mapping)

    if normalized.isna().any():
        bad = series[normalized.isna()].astype(str).unique().tolist()

        raise ValueError(f"Unexpected boolean values: {bad}")

    return normalized.astype(bool)


def finite_non_null(
    series: pd.Series,
) -> bool:
    values = pd.to_numeric(
        series.dropna(),
        errors="coerce",
    )

    if values.isna().any():
        return False

    return all(math.isfinite(float(value)) for value in values)


def summarize_metric(
    frame: pd.DataFrame,
    *,
    metric: str,
    scope: str,
    mic: str | None,
    comparability: str,
) -> dict[str, Any]:
    numeric = pd.to_numeric(
        frame[metric],
        errors="coerce",
    )

    valid = numeric.dropna()

    result: dict[
        str,
        Any,
    ] = {
        "scope": scope,
        "reference_mic": (mic if mic is not None else ""),
        "metric": metric,
        "comparability": comparability,
        "rows": len(frame),
        "non_null": len(valid),
        "missing": int(numeric.isna().sum()),
    }

    if valid.empty:
        for label in (
            "mean",
            "std",
            "q00",
            "q01",
            "q05",
            "q10",
            "q25",
            "q50",
            "q75",
            "q90",
            "q95",
            "q99",
            "q100",
        ):
            result[label] = None

        return result

    result["mean"] = float(valid.mean())

    result["std"] = float(valid.std(ddof=1))

    quantiles = valid.quantile(QUANTILES)

    labels = {
        0.00: "q00",
        0.01: "q01",
        0.05: "q05",
        0.10: "q10",
        0.25: "q25",
        0.50: "q50",
        0.75: "q75",
        0.90: "q90",
        0.95: "q95",
        0.99: "q99",
        1.00: "q100",
    }

    for quantile, label in labels.items():
        result[label] = float(quantiles.loc[quantile])

    return result


def tail_records(
    frame: pd.DataFrame,
    *,
    metric: str,
    scope: str,
    mic: str | None,
    count: int,
) -> list[dict[str, Any]]:
    subset = frame[
        [
            "trading_line_id",
            "security_id",
            "ticker",
            "display_name",
            "reference_mic",
            "as_of_date",
            "available_sessions",
            metric,
        ]
    ].copy()

    subset[metric] = pd.to_numeric(
        subset[metric],
        errors="coerce",
    )

    subset = subset.dropna(subset=[metric])

    if subset.empty:
        return []

    records: list[dict[str, Any]] = []

    for direction, part in (
        (
            "LOW",
            subset.nsmallest(
                count,
                metric,
            ),
        ),
        (
            "HIGH",
            subset.nlargest(
                count,
                metric,
            ),
        ),
    ):
        for rank, row in enumerate(
            part.itertuples(index=False),
            start=1,
        ):
            records.append(
                {
                    "scope": scope,
                    "scope_mic": (mic if mic is not None else ""),
                    "metric": metric,
                    "direction": direction,
                    "rank": rank,
                    "trading_line_id": row.trading_line_id,
                    "security_id": row.security_id,
                    "ticker": row.ticker,
                    "display_name": row.display_name,
                    "reference_mic": row.reference_mic,
                    "as_of_date": row.as_of_date,
                    "available_sessions": row.available_sessions,
                    "value": getattr(
                        row,
                        metric,
                    ),
                }
            )

    return records


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)

    if not SOURCE_MANIFEST.exists():
        raise FileNotFoundError(SOURCE_MANIFEST)

    data = pd.read_csv(
        SOURCE,
        sep="\t",
    )

    print("=" * 100)
    print("V1B2E — POPULATION DISTRIBUTION & QUALITY AUDIT")
    print("=" * 100)

    status_counts = {str(key): int(value) for key, value in data["status"].value_counts().items()}

    print()
    print(
        "ROWS:",
        len(data),
    )

    print(
        "STATUS COUNTS:",
        status_counts,
    )

    passed = data[data["status"] == "PASS"].copy()

    no_history = data[data["status"] == "NO_HISTORY"].copy()

    # ========================================================
    # Normalize boolean coverage columns.
    # ========================================================

    bool_columns = (
        "has_1m",
        "has_3m",
        "has_6m",
        "has_volatility_60d",
        "has_drawdown_252d",
        "has_liquidity_20d",
    )

    for column in bool_columns:
        passed[column] = as_bool_series(passed[column])

    # ========================================================
    # Date / freshness diagnostics.
    # ========================================================

    parsed_dates = pd.to_datetime(
        passed["as_of_date"],
        errors="coerce",
    )

    passed["as_of_age_days"] = [
        (OBSERVED_DATE - timestamp.date()).days if not pd.isna(timestamp) else None
        for timestamp in parsed_dates
    ]

    passed["fresh_7d"] = passed["as_of_age_days"].fillna(10**9) <= 7

    passed["stale_30d"] = passed["as_of_age_days"].fillna(10**9) > 30

    print()
    print("=" * 100)
    print("FEATURE COVERAGE")
    print("=" * 100)

    for column in bool_columns:
        count = int(passed[column].sum())

        print(
            f"{column:30s}",
            f"{count}/{len(passed)}",
        )

    print()
    print("=" * 100)
    print("FRESHNESS BY MIC")
    print("=" * 100)

    for mic in EXPECTED_MICS:
        part = passed[passed["reference_mic"] == mic]

        fresh = int(part["fresh_7d"].sum())

        stale_30 = int(part["stale_30d"].sum())

        age_numeric = pd.to_numeric(
            part["as_of_age_days"],
            errors="coerce",
        )

        print(
            f"{mic:6s}",
            f"pass={len(part):3d}",
            f"fresh<=7d={fresh:3d}",
            f"stale>30d={stale_30:3d}",
            "age[min/median/max]="
            f"{int(age_numeric.min())}/"
            f"{age_numeric.median():.1f}/"
            f"{int(age_numeric.max())}",
        )

    # ========================================================
    # Distribution summaries.
    # ========================================================

    summary_records: list[dict[str, Any]] = []

    for metric in GLOBAL_METRICS:
        summary_records.append(
            summarize_metric(
                passed,
                metric=metric,
                scope="GLOBAL",
                mic=None,
                comparability=("cross_market"),
            )
        )

    for mic in EXPECTED_MICS:
        part = passed[passed["reference_mic"] == mic]

        for metric in GLOBAL_METRICS:
            summary_records.append(
                summarize_metric(
                    part,
                    metric=metric,
                    scope="MIC",
                    mic=mic,
                    comparability=("cross_market"),
                )
            )

        for metric in MIC_DIAGNOSTIC_METRICS:
            summary_records.append(
                summarize_metric(
                    part,
                    metric=metric,
                    scope="MIC",
                    mic=mic,
                    comparability=("within_mic_diagnostic_only"),
                )
            )

    summary = pd.DataFrame(summary_records)

    print()
    print("=" * 100)
    print("GLOBAL DISTRIBUTIONS")
    print("=" * 100)

    printable = summary[
        (summary["scope"] == "GLOBAL") & (summary["metric"] != "available_sessions")
    ][
        [
            "metric",
            "non_null",
            "missing",
            "q00",
            "q01",
            "q05",
            "q50",
            "q95",
            "q99",
            "q100",
        ]
    ]

    print(
        printable.to_string(
            index=False,
            float_format=lambda value: f"{value:.6f}",
        )
    )

    # ========================================================
    # Quality flags.
    # ========================================================

    quality = passed[
        [
            "trading_line_id",
            "security_id",
            "ticker",
            "display_name",
            "reference_mic",
            "provider",
            "provider_mic",
            "adjustment_basis",
            "as_of_date",
            "available_sessions",
            "as_of_age_days",
            *bool_columns,
        ]
    ].copy()

    quality["flag_stale_gt_7d"] = quality["as_of_age_days"] > 7

    quality["flag_stale_gt_30d"] = quality["as_of_age_days"] > 30

    quality["flag_missing_1m"] = ~quality["has_1m"]

    quality["flag_missing_3m"] = ~quality["has_3m"]

    quality["flag_missing_6m"] = ~quality["has_6m"]

    quality["flag_missing_vol60"] = ~quality["has_volatility_60d"]

    quality["flag_missing_dd252"] = ~quality["has_drawdown_252d"]

    quality["flag_missing_liq20"] = ~quality["has_liquidity_20d"]

    flag_columns = (
        "flag_stale_gt_7d",
        "flag_stale_gt_30d",
        "flag_missing_1m",
        "flag_missing_3m",
        "flag_missing_6m",
        "flag_missing_vol60",
        "flag_missing_dd252",
        "flag_missing_liq20",
    )

    quality["any_quality_flag"] = quality[list(flag_columns)].any(axis=1)

    quality_flagged = quality[quality["any_quality_flag"]].copy()

    no_history_quality = no_history[
        [
            "trading_line_id",
            "security_id",
            "ticker",
            "display_name",
            "reference_mic",
            "provider",
            "provider_mic",
            "adjustment_basis",
            "as_of_date",
            "available_sessions",
        ]
    ].copy()

    if not no_history_quality.empty:
        no_history_quality["as_of_age_days"] = None

        for column in bool_columns:
            no_history_quality[column] = False

        for column in flag_columns:
            no_history_quality[column] = False

        no_history_quality["flag_no_history"] = True

        no_history_quality["any_quality_flag"] = True

    quality_flagged["flag_no_history"] = False

    combined_quality = pd.concat(
        [
            quality_flagged,
            no_history_quality,
        ],
        ignore_index=True,
        sort=False,
    )

    print()
    print("=" * 100)
    print("QUALITY FLAGS")
    print("=" * 100)

    print(
        "PASS LINES WITH ANY FLAG:",
        len(quality_flagged),
        "/",
        len(passed),
    )

    print(
        "NO_HISTORY:",
        len(no_history),
    )

    for column in flag_columns:
        print(
            f"{column:30s}",
            int(quality[column].sum()),
        )

    # ========================================================
    # Tail observations.
    # ========================================================

    tail_rows: list[dict[str, Any]] = []

    for metric in GLOBAL_METRICS[1:]:
        tail_rows.extend(
            tail_records(
                passed,
                metric=metric,
                scope="GLOBAL",
                mic=None,
                count=10,
            )
        )

    # Currency/scale-sensitive diagnostics only within MIC.
    for mic in EXPECTED_MICS:
        part = passed[passed["reference_mic"] == mic]

        for metric in MIC_DIAGNOSTIC_METRICS:
            tail_rows.extend(
                tail_records(
                    part,
                    metric=metric,
                    scope="MIC",
                    mic=mic,
                    count=5,
                )
            )

    tails = pd.DataFrame(tail_rows)

    # ========================================================
    # Scientific hard gates.
    # ========================================================

    sessions = pd.to_numeric(
        passed["available_sessions"],
        errors="coerce",
    )

    coverage_semantics: dict[
        str,
        bool,
    ] = {}

    for column, minimum in FEATURE_RULES.items():
        expected = sessions >= minimum

        actual = passed[column]

        coverage_semantics[column] = bool((expected == actual).all())

    finite_gates = {metric: finite_non_null(passed[metric]) for metric in (GLOBAL_METRICS[1:])}

    volatility = pd.to_numeric(
        passed["volatility_60d_annualized"],
        errors="coerce",
    )

    current_dd = pd.to_numeric(
        passed["current_drawdown_252d"],
        errors="coerce",
    )

    max_dd = pd.to_numeric(
        passed["max_drawdown_252d"],
        errors="coerce",
    )

    latest_close = pd.to_numeric(
        passed["latest_close"],
        errors="coerce",
    )

    mtaa = passed[passed["reference_mic"] == "MTAA"]

    non_mtaa = passed[passed["reference_mic"] != "MTAA"]

    no_history_feature_values = (
        "momentum_1m",
        "momentum_3m",
        "momentum_6m",
        "volatility_60d_annualized",
        "current_drawdown_252d",
        "max_drawdown_252d",
        "median_shares_20d",
        "median_trades_20d",
        "median_turnover_20d",
        "median_vwap_20d",
    )

    no_history_values_empty = bool(no_history[list(no_history_feature_values)].isna().all().all())

    hard_gates = {
        "population_971": len(data) == 971,
        "status_counts_exact": status_counts == EXPECTED_STATUS_COUNTS,
        "unique_trading_lines": not data["trading_line_id"].duplicated().any(),
        "all_7_mics_present": set(data["reference_mic"].astype(str)) == set(EXPECTED_MICS),
        "hal_is_only_no_history": (
            len(no_history) == 1
            and str(no_history.iloc[0]["trading_line_id"]) == "BMG455841020-XAMS"
        ),
        "no_history_feature_values_empty": no_history_values_empty,
        "pass_sessions_positive": bool((sessions > 0).all()),
        "pass_latest_close_positive": bool((latest_close > 0).all()),
        "no_future_as_of_dates": bool((passed["as_of_age_days"] >= 0).all()),
        "1m_coverage_exact": coverage_semantics["has_1m"],
        "3m_coverage_exact": coverage_semantics["has_3m"],
        "6m_coverage_exact": coverage_semantics["has_6m"],
        "vol60_coverage_exact": coverage_semantics["has_volatility_60d"],
        "dd252_coverage_exact": coverage_semantics["has_drawdown_252d"],
        "liquidity_true_requires_20_sessions": bool(
            (sessions[passed["has_liquidity_20d"]] >= 20).all()
        ),
        "momentum_1m_finite": finite_gates["momentum_1m"],
        "momentum_3m_finite": finite_gates["momentum_3m"],
        "momentum_6m_finite": finite_gates["momentum_6m"],
        "volatility_finite": finite_gates["volatility_60d_annualized"],
        "current_drawdown_finite": finite_gates["current_drawdown_252d"],
        "max_drawdown_finite": finite_gates["max_drawdown_252d"],
        "volatility_nonnegative": bool((volatility.dropna() >= 0).all()),
        "current_drawdown_in_range": bool(
            ((current_dd.dropna() >= -1) & (current_dd.dropna() <= 0)).all()
        ),
        "max_drawdown_in_range": bool(((max_dd.dropna() >= -1) & (max_dd.dropna() <= 0)).all()),
        "max_dd_not_less_severe_than_current": bool(
            (max_dd.dropna() <= current_dd.loc[max_dd.dropna().index] + 1e-12).all()
        ),
        "mtaa_provider_mapping": bool(
            (mtaa["provider"] == "borsa_italiana_chart_api").all()
            and (mtaa["provider_mic"] == "XMIL").all()
            and (mtaa["adjustment_basis"] == "corporate_action_adjusted").all()
        ),
        "non_mtaa_provider_mapping": bool(
            (non_mtaa["provider"] == "euronext_full_download_csv").all()
            and (non_mtaa["provider_mic"] == non_mtaa["reference_mic"]).all()
            and (non_mtaa["adjustment_basis"] == "provider_default").all()
        ),
    }

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed_gate in hard_gates.items():
        print(
            f"{name:50s}",
            ("PASS" if passed_gate else "FAIL"),
        )

    failed = [name for name, passed_gate in hard_gates.items() if not passed_gate]

    # Write evidence even if a scientific gate fails.
    summary.to_csv(
        SUMMARY_OUTPUT,
        sep="\t",
        index=False,
    )

    combined_quality.to_csv(
        QUALITY_OUTPUT,
        sep="\t",
        index=False,
    )

    tails.to_csv(
        TAILS_OUTPUT,
        sep="\t",
        index=False,
    )

    manifest = {
        "milestone": "V1B2E",
        "source": str(SOURCE),
        "source_sha256": sha256_file(SOURCE),
        "source_manifest": str(SOURCE_MANIFEST),
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "observed_date": OBSERVED_DATE.isoformat(),
        "status_counts": status_counts,
        "pass_count": len(passed),
        "no_history_count": len(no_history),
        "quality_flagged_pass_count": len(quality_flagged),
        "hard_gates": hard_gates,
        "scoring_authorized": False,
        "winsorization_frozen": False,
        "percentile_mapping_frozen": False,
        "open_methodological_issue": (
            "MTAA prices are explicitly "
            "corporate-action adjusted while "
            "non-MTAA Euronext CSV adjustment "
            "semantics remain provider_default."
        ),
        "outputs": {
            "summary": str(SUMMARY_OUTPUT),
            "quality_flags": str(QUALITY_OUTPUT),
            "tails": str(TAILS_OUTPUT),
        },
    }

    MANIFEST_OUTPUT.write_text(
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
        SUMMARY_OUTPUT,
    )

    print(
        "QUALITY:",
        QUALITY_OUTPUT,
    )

    print(
        "TAILS:",
        TAILS_OUTPUT,
    )

    print(
        "MANIFEST:",
        MANIFEST_OUTPUT,
    )

    print()

    if failed:
        print("STATUS: FAIL")

        raise RuntimeError(f"Failed gates: {failed}")

    print("STATUS: PASS")


if __name__ == "__main__":
    main()
