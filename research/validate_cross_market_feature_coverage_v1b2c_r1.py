from __future__ import annotations

from pathlib import Path

import pandas as pd

SOURCE = Path("research") / "v1b2c_cross_market_feature_coverage.tsv"

EXPECTED_MICS = (
    "MTAA",
    "XAMS",
    "XBRU",
    "XLIS",
    "XMSM",
    "XOSL",
    "XPAR",
)

COVERAGE_RULES = {
    "has_1m": 22,
    "has_3m": 64,
    "has_6m": 127,
    "has_volatility_60d": 61,
    "has_drawdown_252d": 252,
    "has_liquidity_20d": 20,
}


def as_bool(
    value: object,
) -> bool:
    if isinstance(
        value,
        bool,
    ):
        return value

    text = str(value).strip().lower()

    if text == "true":
        return True

    if text == "false":
        return False

    raise ValueError(f"Unexpected boolean value: {value!r}")


def main() -> None:
    data = pd.read_csv(
        SOURCE,
        sep="\t",
    )

    print("=" * 100)
    print("V1B2C-R1 — STATIC FEATURE COVERAGE VALIDATOR")
    print("=" * 100)

    print()
    print(
        "ROWS:",
        len(data),
    )

    successful = data[data["status"] == "PASS"].copy()

    print(
        "FETCH PASS:",
        len(successful),
        "/",
        len(data),
    )

    print()
    print("=" * 100)
    print("INSUFFICIENT-HISTORY LINES")
    print("=" * 100)

    incomplete = successful[successful["available_sessions"] < 252].copy()

    if incomplete.empty:
        print("NONE")

    else:
        columns = [
            "reference_mic",
            "trading_line_id",
            "display_name",
            "available_sessions",
            "has_1m",
            "has_3m",
            "has_6m",
            "has_volatility_60d",
            "has_drawdown_252d",
            "has_liquidity_20d",
        ]

        print(incomplete[columns].to_string(index=False))

    print()
    print("=" * 100)
    print("COVERAGE SEMANTICS")
    print("=" * 100)

    semantic_results: dict[
        str,
        bool,
    ] = {}

    for column, required_sessions in COVERAGE_RULES.items():
        actual = successful[column].map(as_bool)

        expected = successful["available_sessions"] >= required_sessions

        matches = actual == expected

        semantic_results[column] = bool(matches.all())

        print()
        print(f"{column}:")

        print(
            "  required sessions:",
            required_sessions,
        )

        print(
            "  available:",
            int(actual.sum()),
            "/",
            len(actual),
        )

        print(
            "  semantic mismatches:",
            int((~matches).sum()),
        )

        if not matches.all():
            bad = successful.loc[
                ~matches,
                [
                    "reference_mic",
                    "trading_line_id",
                    "display_name",
                    "available_sessions",
                    column,
                ],
            ]

            print(bad.to_string(index=False))

    counts = data["reference_mic"].value_counts().to_dict()

    hard_gates = {
        "exactly_56_frozen_lines": len(data) == 56,
        "all_56_fetches_passed": len(successful) == 56,
        "all_7_mics_present": set(data["reference_mic"]) == set(EXPECTED_MICS),
        "exactly_8_lines_per_mic": all(
            counts.get(
                mic,
                0,
            )
            == 8
            for mic in EXPECTED_MICS
        ),
        "no_duplicate_trading_lines": not data["trading_line_id"].duplicated().any(),
        "1m_coverage_semantics": semantic_results["has_1m"],
        "3m_coverage_semantics": semantic_results["has_3m"],
        "6m_coverage_semantics": semantic_results["has_6m"],
        "vol60_coverage_semantics": semantic_results["has_volatility_60d"],
        "drawdown_coverage_semantics": semantic_results["has_drawdown_252d"],
        "liquidity_coverage_semantics": semantic_results["has_liquidity_20d"],
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

    failed = [name for name, passed in hard_gates.items() if not passed]

    print()

    if failed:
        print("STATUS: FAIL")

        raise RuntimeError(f"Failed gates: {failed}")

    print("STATUS: PASS")

    print()
    print("INTERPRETATION:")

    print(
        "Missing features caused by insufficient "
        "history are expected data-coverage states, "
        "not provider failures."
    )


if __name__ == "__main__":
    main()
