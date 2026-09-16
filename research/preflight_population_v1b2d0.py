from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

BASE = Path("data") / "snapshots" / "2026-09-13" / "canonical"

TRADING_LINES_PATH = BASE / "trading_lines.parquet"

CLASSIFICATION_PATH = BASE / "instrument_classification.parquet"

OUTPUT = Path("research") / "v1b2d0_population_preflight.json"


def safe_value(
    value: Any,
) -> Any:
    if pd.isna(value):
        return None

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


def low_cardinality_summary(
    frame: pd.DataFrame,
) -> dict[
    str,
    Any,
]:
    result: dict[
        str,
        Any,
    ] = {}

    for column in frame.columns:
        series = frame[column]

        non_null = series.dropna()

        unique_count = int(non_null.nunique(dropna=True))

        if unique_count <= 20:
            counts = non_null.value_counts(dropna=False)

            result[str(column)] = {
                "dtype": str(series.dtype),
                "unique_count": unique_count,
                "values": [
                    {
                        "value": safe_value(value),
                        "count": int(count),
                    }
                    for value, count in counts.items()
                ],
            }

    return result


def main() -> None:
    trading = pd.read_parquet(TRADING_LINES_PATH)

    classification = pd.read_parquet(CLASSIFICATION_PATH)

    print("=" * 100)
    print("V1B2D0 — REGULATED COMMON-STOCK POPULATION PREFLIGHT")
    print("=" * 100)

    print()
    print(
        "TRADING LINES:",
        len(trading),
    )

    print(
        "CLASSIFICATION ROWS:",
        len(classification),
    )

    print()
    print("=" * 100)
    print("TRADING LINE COLUMNS")
    print("=" * 100)

    for column in trading.columns:
        print(
            f"{column:35s}",
            trading[column].dtype,
        )

    print()
    print("=" * 100)
    print("CLASSIFICATION COLUMNS")
    print("=" * 100)

    for column in classification.columns:
        print(
            f"{column:35s}",
            classification[column].dtype,
        )

    print()
    print("=" * 100)
    print("CLASSIFICATION LOW-CARDINALITY VALUES")
    print("=" * 100)

    summaries = low_cardinality_summary(classification)

    for column, summary in summaries.items():
        print()
        print(
            column,
            "|",
            summary["dtype"],
        )

        for item in summary["values"]:
            print(
                " ",
                repr(item["value"]),
                "=>",
                item["count"],
            )

    hard_gates: dict[
        str,
        bool,
    ] = {
        "trading_lines_1011": len(trading) == 1011,
        "classification_1011": len(classification) == 1011,
        "trading_line_id_in_trading": ("trading_line_id" in trading.columns),
        "trading_line_id_in_classification": ("trading_line_id" in classification.columns),
    }

    if "trading_line_id" in trading.columns and "trading_line_id" in classification.columns:
        trading_ids = set(trading["trading_line_id"].astype(str))

        classification_ids = set(classification["trading_line_id"].astype(str))

        hard_gates["trading_ids_unique"] = not trading["trading_line_id"].duplicated().any()

        hard_gates["classification_ids_unique"] = (
            not classification["trading_line_id"].duplicated().any()
        )

        hard_gates["exact_line_set_match"] = trading_ids == classification_ids

        print()
        print(
            "TRADING IDS ONLY:",
            len(trading_ids - classification_ids),
        )

        print(
            "CLASSIFICATION IDS ONLY:",
            len(classification_ids - trading_ids),
        )

    print()
    print("=" * 100)
    print("HARD GATES")
    print("=" * 100)

    for name, passed in hard_gates.items():
        print(
            f"{name:40s}",
            ("PASS" if passed else "FAIL"),
        )

    artifact = {
        "snapshot": "2026-09-13",
        "trading_lines_path": str(TRADING_LINES_PATH),
        "classification_path": str(CLASSIFICATION_PATH),
        "trading_line_rows": len(trading),
        "classification_rows": len(classification),
        "trading_line_columns": {
            str(column): str(trading[column].dtype) for column in trading.columns
        },
        "classification_columns": {
            str(column): str(classification[column].dtype) for column in classification.columns
        },
        "classification_low_cardinality": summaries,
        "hard_gates": hard_gates,
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
    print(
        "WROTE:",
        OUTPUT,
    )

    failed = [name for name, passed in hard_gates.items() if not passed]

    if failed:
        raise RuntimeError(f"Failed gates: {failed}")

    print()
    print("STATUS: PASS")


if __name__ == "__main__":
    main()
