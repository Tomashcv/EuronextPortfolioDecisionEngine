from __future__ import annotations

import math

import httpx

from euronext_pde.features.market import (
    compute_market_risk_features,
)
from euronext_pde.providers.historical_market_data import (
    RoutingHistoricalMarketDataProvider,
)

PROBES = (
    {
        "label": "Paris — STMicroelectronics",
        "trading_line_id": "NL0000226223-XPAR",
        "security_id": "NL0000226223",
        "reference_mic": "XPAR",
    },
    {
        "label": "Milan — FNM",
        "trading_line_id": "IT0000060886-MTAA",
        "security_id": "IT0000060886",
        "reference_mic": "MTAA",
    },
)


def pct(
    value: float | None,
) -> str:
    if value is None:
        return "N/A"

    return f"{100.0 * value:.2f}%"


def number(
    value: float | None,
) -> str:
    if value is None:
        return "N/A"

    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"

    if abs(value) >= 1_000:
        return f"{value / 1_000:.2f}K"

    return f"{value:.2f}"


def main() -> None:
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

    hard_gates: dict[
        str,
        bool,
    ] = {}

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        provider = RoutingHistoricalMarketDataProvider(client)

        print("=" * 100)
        print("V1B2B — LIVE MARKET/RISK FEATURE SMOKE TEST")
        print("=" * 100)

        for probe in PROBES:
            rows = provider.fetch(
                trading_line_id=(probe["trading_line_id"]),
                security_id=(probe["security_id"]),
                reference_mic=(probe["reference_mic"]),
            )

            features = compute_market_risk_features(rows)

            print()
            print("=" * 100)
            print(probe["label"])
            print("=" * 100)

            print(
                "AS OF:",
                features.as_of_date,
            )

            print(
                "SESSIONS:",
                features.available_sessions,
            )

            print(
                "PROVIDER:",
                features.provider,
            )

            print(
                "PROVIDER MIC:",
                features.provider_mic,
            )

            print(
                "ADJUSTMENT:",
                features.adjustment_basis.value,
            )

            print()
            print(
                "MOMENTUM 1M:",
                pct(features.momentum_1m),
            )

            print(
                "MOMENTUM 3M:",
                pct(features.momentum_3m),
            )

            print(
                "MOMENTUM 6M:",
                pct(features.momentum_6m),
            )

            print()
            print(
                "VOLATILITY 60D ANN.:",
                pct(features.volatility_60d_annualized),
            )

            print(
                "CURRENT DD 252D:",
                pct(features.current_drawdown_252d),
            )

            print(
                "MAX DD 252D:",
                pct(features.max_drawdown_252d),
            )

            print()
            print(
                "MEDIAN SHARES 20D:",
                number(features.median_shares_20d),
            )

            print(
                "MEDIAN TRADES 20D:",
                number(features.median_trades_20d),
            )

            print(
                "MEDIAN TURNOVER 20D:",
                number(features.median_turnover_20d),
            )

            print(
                "MEDIAN VWAP 20D:",
                number(features.median_vwap_20d),
            )

            prefix = str(probe["reference_mic"]).lower()

            hard_gates[f"{prefix}_has_1m"] = features.has_1m

            hard_gates[f"{prefix}_has_3m"] = features.has_3m

            hard_gates[f"{prefix}_has_6m"] = features.has_6m

            hard_gates[f"{prefix}_has_volatility"] = features.has_volatility_60d

            hard_gates[f"{prefix}_has_drawdown"] = features.has_drawdown_252d

            hard_gates[f"{prefix}_has_liquidity"] = features.has_liquidity_20d

            hard_gates[f"{prefix}_volatility_nonnegative"] = (
                features.volatility_60d_annualized is not None
                and features.volatility_60d_annualized >= 0.0
            )

            hard_gates[f"{prefix}_drawdowns_nonpositive"] = (
                features.current_drawdown_252d is not None
                and features.max_drawdown_252d is not None
                and features.current_drawdown_252d <= 0.0
                and features.max_drawdown_252d <= 0.0
            )

            numeric_values = (
                features.momentum_1m,
                features.momentum_3m,
                features.momentum_6m,
                features.volatility_60d_annualized,
                features.current_drawdown_252d,
                features.max_drawdown_252d,
                features.median_shares_20d,
                features.median_trades_20d,
                features.median_turnover_20d,
                features.median_vwap_20d,
            )

            hard_gates[f"{prefix}_all_finite"] = all(
                value is None or math.isfinite(value) for value in numeric_values
            )

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:45s}",
            ("PASS" if passed else "FAIL"),
        )

    failed = [name for name, passed in hard_gates.items() if not passed]

    print()

    if failed:
        print("STATUS: FAIL")

        raise RuntimeError(f"Failed gates: {failed}")

    print("STATUS: PASS")


if __name__ == "__main__":
    main()
