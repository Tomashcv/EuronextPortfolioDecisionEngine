from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SOURCE = Path("research") / "v1b2d_r1_population_market_features.tsv"

OUTPUT = Path("research") / "v1b2f_outlier_triage.tsv"

MANIFEST = Path("research") / "v1b2f_outlier_triage_manifest.json"


def main() -> None:
    data = pd.read_csv(
        SOURCE,
        sep="\t",
    )

    passed = data[data["status"] == "PASS"].copy()

    numeric_columns = (
        "available_sessions",
        "momentum_1m",
        "momentum_3m",
        "momentum_6m",
        "volatility_60d_annualized",
        "current_drawdown_252d",
        "max_drawdown_252d",
        "median_trades_20d",
        "median_turnover_20d",
        "median_shares_20d",
        "latest_close",
    )

    for column in numeric_columns:
        passed[column] = pd.to_numeric(
            passed[column],
            errors="coerce",
        )

    as_of = pd.to_datetime(
        passed["as_of_date"],
        errors="coerce",
    )

    observed = pd.Timestamp("2026-09-14")

    passed["age_days"] = (observed - as_of).dt.days

    # --------------------------------------------------------
    # Diagnostic flags only.
    # These are NOT production thresholds.
    # --------------------------------------------------------

    passed["flag_stale_gt_7d"] = passed["age_days"] > 7

    passed["flag_stale_gt_30d"] = passed["age_days"] > 30

    passed["flag_zero_vol"] = passed["volatility_60d_annualized"].fillna(float("inf")) <= 1e-12

    passed["flag_very_low_activity"] = passed["median_trades_20d"].fillna(float("inf")) <= 5

    passed["flag_low_activity"] = passed["median_trades_20d"].fillna(float("inf")) <= 20

    passed["flag_1m_abs_gt_100pct"] = passed["momentum_1m"].abs().fillna(0.0) > 1.0

    passed["flag_3m_abs_gt_100pct"] = passed["momentum_3m"].abs().fillna(0.0) > 1.0

    passed["flag_6m_abs_gt_100pct"] = passed["momentum_6m"].abs().fillna(0.0) > 1.0

    passed["flag_vol_gt_150pct"] = passed["volatility_60d_annualized"].fillna(0.0) > 1.5

    passed["flag_vol_gt_300pct"] = passed["volatility_60d_annualized"].fillna(0.0) > 3.0

    passed["flag_current_dd_gt_90pct"] = passed["current_drawdown_252d"].fillna(0.0) < -0.90

    passed["flag_max_dd_gt_90pct"] = passed["max_drawdown_252d"].fillna(0.0) < -0.90

    flag_columns = [column for column in passed.columns if column.startswith("flag_")]

    passed["diagnostic_flag_count"] = passed[flag_columns].sum(axis=1)

    flagged = passed[passed["diagnostic_flag_count"] > 0].copy()

    flagged = flagged.sort_values(
        [
            "diagnostic_flag_count",
            "reference_mic",
            "trading_line_id",
        ],
        ascending=[
            False,
            True,
            True,
        ],
    )

    columns = [
        "reference_mic",
        "trading_line_id",
        "ticker",
        "display_name",
        "as_of_date",
        "age_days",
        "available_sessions",
        "latest_close",
        "momentum_1m",
        "momentum_3m",
        "momentum_6m",
        "volatility_60d_annualized",
        "current_drawdown_252d",
        "max_drawdown_252d",
        "median_trades_20d",
        "median_turnover_20d",
        "diagnostic_flag_count",
        *flag_columns,
    ]

    flagged[columns].to_csv(
        OUTPUT,
        sep="\t",
        index=False,
    )

    print("=" * 110)
    print("V1B2F — OUTLIER / DATA-QUALITY TRIAGE")
    print("=" * 110)

    print()
    print(
        "PASS POPULATION:",
        len(passed),
    )

    print(
        "LINES WITH >=1 DIAGNOSTIC FLAG:",
        len(flagged),
    )

    print()
    print("=" * 110)
    print("FLAG COUNTS")
    print("=" * 110)

    for column in flag_columns:
        print(
            f"{column:35s}",
            int(passed[column].sum()),
        )

    print()
    print("=" * 110)
    print("STALE LINES")
    print("=" * 110)

    stale = passed[passed["flag_stale_gt_7d"]][
        [
            "reference_mic",
            "trading_line_id",
            "display_name",
            "as_of_date",
            "age_days",
            "available_sessions",
        ]
    ].sort_values(
        "age_days",
        ascending=False,
    )

    print(stale.to_string(index=False) if not stale.empty else "NONE")

    print()
    print("=" * 110)
    print("ZERO-VOLATILITY LINES")
    print("=" * 110)

    zero_vol = passed[passed["flag_zero_vol"]][
        [
            "reference_mic",
            "trading_line_id",
            "display_name",
            "latest_close",
            "median_trades_20d",
            "median_turnover_20d",
            "volatility_60d_annualized",
        ]
    ].sort_values(
        [
            "reference_mic",
            "trading_line_id",
        ]
    )

    print(zero_vol.to_string(index=False) if not zero_vol.empty else "NONE")

    print()
    print("=" * 110)
    print("EXTREME MOMENTUM / VOLATILITY CANDIDATES")
    print("=" * 110)

    extreme = passed[
        (passed["flag_1m_abs_gt_100pct"])
        | (passed["flag_3m_abs_gt_100pct"])
        | (passed["flag_6m_abs_gt_100pct"])
        | (passed["flag_vol_gt_150pct"])
    ][
        [
            "reference_mic",
            "trading_line_id",
            "display_name",
            "latest_close",
            "momentum_1m",
            "momentum_3m",
            "momentum_6m",
            "volatility_60d_annualized",
            "median_trades_20d",
            "median_turnover_20d",
        ]
    ].sort_values(
        "volatility_60d_annualized",
        ascending=False,
    )

    print(
        extreme.to_string(
            index=False,
            float_format=lambda value: f"{value:.6f}",
        )
        if not extreme.empty
        else "NONE"
    )

    print()
    print("=" * 110)
    print("LOW-ACTIVITY CANDIDATES")
    print("=" * 110)

    low_activity = passed[passed["flag_low_activity"]][
        [
            "reference_mic",
            "trading_line_id",
            "display_name",
            "latest_close",
            "median_trades_20d",
            "median_turnover_20d",
            "volatility_60d_annualized",
            "momentum_1m",
            "momentum_3m",
            "momentum_6m",
        ]
    ].sort_values(
        [
            "median_trades_20d",
            "reference_mic",
        ]
    )

    print(
        low_activity.head(50).to_string(
            index=False,
            float_format=lambda value: f"{value:.6f}",
        )
        if not low_activity.empty
        else "NONE"
    )

    print()
    print("=" * 110)
    print("TOP 25 MOST FLAGGED")
    print("=" * 110)

    print(
        flagged[
            [
                "reference_mic",
                "trading_line_id",
                "display_name",
                "diagnostic_flag_count",
                "age_days",
                "latest_close",
                "momentum_1m",
                "momentum_3m",
                "momentum_6m",
                "volatility_60d_annualized",
                "max_drawdown_252d",
                "median_trades_20d",
            ]
        ]
        .head(25)
        .to_string(
            index=False,
            float_format=lambda value: f"{value:.6f}",
        )
    )

    manifest = {
        "milestone": "V1B2F",
        "source": str(SOURCE),
        "pass_population": len(passed),
        "flagged_count": len(flagged),
        "diagnostic_thresholds_only": True,
        "production_filters_frozen": False,
        "winsorization_frozen": False,
        "scoring_authorized": False,
        "flag_counts": {column: int(passed[column].sum()) for column in flag_columns},
        "output": str(OUTPUT),
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
        "MANIFEST:",
        MANIFEST,
    )

    print()
    print("STATUS: PASS")


if __name__ == "__main__":
    main()
