from __future__ import annotations

from datetime import UTC, datetime

import httpx

from euronext_pde.market_data import (
    DailyMarketObservation,
)
from euronext_pde.providers.historical_market_data import (
    BORSA_PROVIDER,
    EURONEXT_PROVIDER,
    RoutingHistoricalMarketDataProvider,
)

PROBES = (
    {
        "label": "Paris — STMicroelectronics",
        "trading_line_id": "NL0000226223-XPAR",
        "security_id": "NL0000226223",
        "reference_mic": "XPAR",
        "expected_provider": EURONEXT_PROVIDER,
    },
    {
        "label": "Milan — FNM",
        "trading_line_id": "IT0000060886-MTAA",
        "security_id": "IT0000060886",
        "reference_mic": "MTAA",
        "expected_provider": BORSA_PROVIDER,
    },
)


def main() -> None:
    today = datetime.now(UTC).date()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/152 Safari/537.36"
        ),
        "Accept-Language": ("en-US,en;q=0.9"),
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
        print("V1B1A — ROUTING PROVIDER LIVE SMOKE TEST")
        print("=" * 100)

        for probe in PROBES:
            print()
            print("=" * 100)
            print(probe["label"])
            print("=" * 100)

            rows = provider.fetch(
                trading_line_id=(probe["trading_line_id"]),
                security_id=(probe["security_id"]),
                reference_mic=(probe["reference_mic"]),
            )

            if not rows:
                raise RuntimeError("Provider returned no rows.")

            first = rows[0]
            last = rows[-1]

            dates = [row.session_date for row in rows]

            unique_dates = set(dates)

            providers = {row.provider for row in rows}

            provider_mics = {row.provider_mic for row in rows}

            adjustment_bases = {row.adjustment_basis.value for row in rows}

            age_days = (today - last.session_date).days

            print(
                "ROWS:",
                len(rows),
            )

            print(
                "FIRST:",
                first.session_date,
            )

            print(
                "LAST:",
                last.session_date,
            )

            print(
                "AGE DAYS:",
                age_days,
            )

            print(
                "PROVIDER:",
                providers,
            )

            print(
                "PROVIDER MIC:",
                provider_mics,
            )

            print(
                "ADJUSTMENT BASIS:",
                adjustment_bases,
            )

            print(
                "LATEST CLOSE:",
                last.close,
            )

            print(
                "LATEST SHARES:",
                last.number_of_shares,
            )

            print(
                "LATEST TRADES:",
                last.number_of_trades,
            )

            print(
                "LATEST TURNOVER:",
                last.turnover,
            )

            print(
                "LATEST VWAP:",
                last.vwap,
            )

            prefix = str(probe["reference_mic"]).lower()

            hard_gates[f"{prefix}_nonempty"] = bool(rows)

            hard_gates[f"{prefix}_canonical_type"] = all(
                isinstance(
                    row,
                    DailyMarketObservation,
                )
                for row in rows
            )

            hard_gates[f"{prefix}_ascending_dates"] = dates == sorted(dates)

            hard_gates[f"{prefix}_unique_dates"] = len(dates) == len(unique_dates)

            hard_gates[f"{prefix}_fresh"] = 0 <= age_days <= 7

            hard_gates[f"{prefix}_provider_correct"] = providers == {probe["expected_provider"]}

            hard_gates[f"{prefix}_identity_preserved"] = all(
                row.trading_line_id == probe["trading_line_id"]
                and row.security_id == probe["security_id"]
                and row.reference_mic == probe["reference_mic"]
                for row in rows
            )

            hard_gates[f"{prefix}_ohlc_valid"] = all(
                row.high
                >= max(
                    row.open,
                    row.close,
                    row.low,
                )
                and row.low
                <= min(
                    row.open,
                    row.close,
                    row.high,
                )
                for row in rows
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
