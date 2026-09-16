from __future__ import annotations

import time
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

SOURCE = Path("research") / "v1b0d_cross_market_historical_coverage.tsv"

OUTPUT = Path("research") / "v1b2c_cross_market_feature_coverage.tsv"

EXPECTED_MICS = (
    "MTAA",
    "XAMS",
    "XBRU",
    "XLIS",
    "XMSM",
    "XOSL",
    "XPAR",
)


def main() -> None:
    source = pd.read_csv(
        SOURCE,
        sep="\t",
    )

    required = {
        "trading_line_id",
        "security_id",
        "reference_mic",
    }

    missing = required - set(source.columns)

    if missing:
        raise RuntimeError(f"Missing source columns: {sorted(missing)}")

    sample = (
        source[source["reference_mic"].isin(EXPECTED_MICS)]
        .drop_duplicates(subset=["trading_line_id"])
        .sort_values(
            [
                "reference_mic",
                "trading_line_id",
            ]
        )
        .reset_index(drop=True)
    )

    counts = sample["reference_mic"].value_counts().to_dict()

    for mic in EXPECTED_MICS:
        if (
            counts.get(
                mic,
                0,
            )
            != 8
        ):
            raise RuntimeError(f"Expected 8 frozen lines for {mic}; found {counts.get(mic, 0)}.")

    if len(sample) != 56:
        raise RuntimeError("Expected exactly 56 frozen lines.")

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

    records: list[dict[str, Any]] = []

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        provider = RoutingHistoricalMarketDataProvider(client)

        for index, row in enumerate(
            sample.itertuples(index=False),
            start=1,
        ):
            trading_line_id = str(row.trading_line_id)

            security_id = str(row.security_id)

            reference_mic = str(row.reference_mic)

            display_name = str(
                getattr(
                    row,
                    "display_name",
                    "",
                )
            )

            print(f"[{index:02d}/56] {reference_mic} {trading_line_id} {display_name}")

            try:
                observations = provider.fetch(
                    trading_line_id=(trading_line_id),
                    security_id=(security_id),
                    reference_mic=(reference_mic),
                )

                features = compute_market_risk_features(observations)

                record = {
                    "trading_line_id": trading_line_id,
                    "security_id": security_id,
                    "reference_mic": reference_mic,
                    "display_name": display_name,
                    "status": "PASS",
                    "error": "",
                    "provider": features.provider,
                    "provider_mic": features.provider_mic,
                    "adjustment_basis": (features.adjustment_basis.value),
                    "as_of_date": features.as_of_date.isoformat(),
                    "available_sessions": features.available_sessions,
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
                }

            except (
                httpx.HTTPError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                record = {
                    "trading_line_id": trading_line_id,
                    "security_id": security_id,
                    "reference_mic": reference_mic,
                    "display_name": display_name,
                    "status": "FAIL",
                    "error": (f"{type(exc).__name__}: {exc}"),
                }

            records.append(record)

            time.sleep(0.15)

    result = pd.DataFrame(records)

    result.to_csv(
        OUTPUT,
        sep="\t",
        index=False,
    )

    print()
    print("=" * 100)
    print("V1B2C — CROSS-MARKET FEATURE COVERAGE")
    print("=" * 100)

    successful = result[result["status"] == "PASS"]

    print(
        "LINES:",
        len(result),
    )

    print(
        "FETCH PASS:",
        len(successful),
        "/",
        len(result),
    )

    print()
    print("BY MIC")

    for mic in EXPECTED_MICS:
        part = result[result["reference_mic"] == mic]

        good = part[part["status"] == "PASS"]

        print()
        print(
            mic,
            f"{len(good)}/{len(part)} fetched",
        )

        if good.empty:
            continue

        for column in (
            "has_1m",
            "has_3m",
            "has_6m",
            "has_volatility_60d",
            "has_drawdown_252d",
            "has_liquidity_20d",
        ):
            count = int(good[column].sum())

            print(f"  {column:25s} {count}/{len(good)}")

        print(
            "  sessions min/median/max "
            f"{int(good['available_sessions'].min())}"
            "/"
            f"{good['available_sessions'].median():.1f}"
            "/"
            f"{int(good['available_sessions'].max())}"
        )

    print()
    print("=" * 100)
    print("GLOBAL FEATURE COVERAGE")
    print("=" * 100)

    if not successful.empty:
        for column in (
            "has_1m",
            "has_3m",
            "has_6m",
            "has_volatility_60d",
            "has_drawdown_252d",
            "has_liquidity_20d",
        ):
            count = int(successful[column].sum())

            print(f"{column:30s} {count}/{len(successful)}")

    failures = result[result["status"] != "PASS"]

    print()
    print(
        "FETCH FAILURES:",
        len(failures),
    )

    if not failures.empty:
        print(
            failures[
                [
                    "reference_mic",
                    "trading_line_id",
                    "error",
                ]
            ].to_string(index=False)
        )

    hard_gates = {
        "all_56_attempted": len(result) == 56,
        "all_7_mics_present": set(result["reference_mic"]) == set(EXPECTED_MICS),
        "all_lines_have_liquidity_if_fetched": (
            successful.empty or successful["has_liquidity_20d"].all()
        ),
        "no_duplicate_trading_lines": (result["trading_line_id"].duplicated().sum() == 0),
    }

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

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
