from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from euronext_pde.providers.historical_market_data import (
    RoutingHistoricalMarketDataProvider,
)

OUTPUT = Path("research") / "v1b2g_targeted_raw_path_audit.json"

TARGETS = (
    (
        "FR001400IE67-XPAR",
        "FR001400IE67",
        "XPAR",
        "MYHOTELMATCH",
    ),
    (
        "FR0010209809-XPAR",
        "FR0010209809",
        "XPAR",
        "SOC FRANC CASINOS",
    ),
    (
        "BE0003748622-XBRU",
        "BE0003748622",
        "XBRU",
        "IEP INVEST",
    ),
    (
        "NO0012916131-XOSL",
        "NO0012916131",
        "XOSL",
        "TECHSTEP",
    ),
    (
        "FR0004052561-XPAR",
        "FR0004052561",
        "XPAR",
        "PROACTIS SA",
    ),
    (
        "FR0013227113-XPAR",
        "FR0013227113",
        "XPAR",
        "SOITEC",
    ),
    (
        "IT0001041000-MTAA",
        "IT0001041000",
        "MTAA",
        "BCO DESIO BRIANZA",
    ),
)

WINDOWS = (
    20,
    60,
    126,
    252,
)


def safe_return(
    previous: float,
    current: float,
) -> float | None:
    if previous <= 0:
        return None

    return current / previous - 1.0


def audit_target(
    rows: list[Any],
    *,
    name: str,
) -> dict[str, Any]:
    if not rows:
        raise RuntimeError(f"No rows for {name}.")

    session_records: list[dict[str, Any]] = []

    one_day_moves: list[
        tuple[
            float,
            dict[str, Any],
        ]
    ] = []

    for index, row in enumerate(rows):
        daily_return = None

        if index > 0:
            previous = rows[index - 1]

            daily_return = safe_return(
                previous.close,
                row.close,
            )

        record = {
            "date": row.session_date.isoformat(),
            "close": row.close,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "shares": row.number_of_shares,
            "trades": row.number_of_trades,
            "turnover": row.turnover,
            "vwap": row.vwap,
            "daily_return": daily_return,
        }

        session_records.append(record)

        if daily_return is not None and math.isfinite(daily_return):
            one_day_moves.append(
                (
                    abs(daily_return),
                    record,
                )
            )

    one_day_moves.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    window_stats: dict[
        str,
        Any,
    ] = {}

    for window in WINDOWS:
        tail = rows[-window:]

        zero_trade_sessions = sum(
            (row.number_of_trades is not None and row.number_of_trades == 0) for row in tail
        )

        missing_trade_sessions = sum(row.number_of_trades is None for row in tail)

        zero_turnover_sessions = sum(
            (row.turnover is not None and row.turnover == 0) for row in tail
        )

        changed_close_sessions = 0

        for previous, current in pairwise(tail):
            if previous.close != current.close:
                changed_close_sessions += 1

        window_stats[str(window)] = {
            "available": len(tail),
            "zero_trade_sessions": zero_trade_sessions,
            "missing_trade_sessions": missing_trade_sessions,
            "zero_turnover_sessions": zero_turnover_sessions,
            "changed_close_sessions": changed_close_sessions,
            "unchanged_close_share": (
                1.0
                - (
                    changed_close_sessions
                    / max(
                        len(tail) - 1,
                        1,
                    )
                )
            ),
        }

    top_moves = [item[1] for item in one_day_moves[:10]]

    return {
        "name": name,
        "provider": rows[0].provider,
        "provider_mic": rows[0].provider_mic,
        "adjustment_basis": rows[0].adjustment_basis.value,
        "rows": len(rows),
        "first_date": rows[0].session_date.isoformat(),
        "last_date": rows[-1].session_date.isoformat(),
        "latest_close": rows[-1].close,
        "window_stats": window_stats,
        "top_10_absolute_daily_moves": top_moves,
        "recent_30_sessions": session_records[-30:],
    }


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

    results: list[dict[str, Any]] = []

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        provider = RoutingHistoricalMarketDataProvider(client)

        for (
            line_id,
            security_id,
            mic,
            name,
        ) in TARGETS:
            print()
            print("=" * 110)
            print(
                name,
                "|",
                line_id,
            )
            print("=" * 110)

            rows = provider.fetch(
                trading_line_id=(line_id),
                security_id=(security_id),
                reference_mic=mic,
            )

            audit = audit_target(
                rows,
                name=name,
            )

            results.append(
                {
                    "trading_line_id": line_id,
                    "security_id": security_id,
                    "reference_mic": mic,
                    **audit,
                }
            )

            print(
                "ROWS:",
                audit["rows"],
            )

            print(
                "RANGE:",
                audit["first_date"],
                "->",
                audit["last_date"],
            )

            print(
                "ADJUSTMENT:",
                audit["adjustment_basis"],
            )

            print()
            print("WINDOW STATS")

            for window, stats in audit["window_stats"].items():
                print(
                    window,
                    stats,
                )

            print()
            print("TOP 10 ABS DAILY MOVES")

            frame = pd.DataFrame(audit["top_10_absolute_daily_moves"])

            if frame.empty:
                print("NONE")

            else:
                print(
                    frame.to_string(
                        index=False,
                        float_format=lambda value: f"{value:.6f}",
                    )
                )

    artifact = {
        "milestone": "V1B2G",
        "purpose": ("Targeted raw-path audit before any winsorization or percentile freeze."),
        "targets": results,
        "winsorization_frozen": False,
        "scoring_authorized": False,
    }

    OUTPUT.write_text(
        json.dumps(
            artifact,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 110)
    print(
        "WROTE:",
        OUTPUT,
    )
    print("=" * 110)

    print()
    print("STATUS: PASS")


if __name__ == "__main__":
    main()
