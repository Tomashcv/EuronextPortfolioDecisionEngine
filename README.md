# Euronext Portfolio Decision Engine

A weekly, human-in-the-loop quantitative portfolio research system for
Euronext-listed equities.

The project is independent and is not affiliated with or endorsed by
Euronext.

## V1 objective

V1 deliberately excludes:

- news;
- geopolitics;
- thematic overlays;
- ETFs;
- machine learning;
- intraday trading.

The baseline pipeline is:

    Euronext equity universe
              ↓
    prices + fundamentals
              ↓
    multidimensional features
              ↓
    State Score
              +
    Trajectory Score
              ↓
    Opportunity Score
              ↓
    weekly portfolio recommendation

## V1 dimensions

- Fundamentals
- Growth
- Valuation
- Market / momentum
- Risk

The first trajectory signal uses slow fundamental change. Higher-order
acceleration and jerk are intentionally deferred until they demonstrate
incremental value.

## Cross-platform design

The repository is designed to run unchanged on Windows and Linux.

Requirements:

- Python 3.12
- uv

No source file should contain machine-specific absolute paths.

### Windows

    uv sync
    uv run epde doctor
    uv run pytest
    uv run ruff check .

### Linux

    uv sync
    uv run epde doctor
    uv run pytest
    uv run ruff check .

The commands are intentionally identical.

## Data policy

Raw third-party market data are not committed.

Point-in-time snapshots will be stored locally under `data/snapshots/`
so future research can distinguish information actually available at a
decision date from subsequently revised data.

## Current milestone

**V1A — Universe and data foundation**

Build a validated Euronext equity universe and define the first
cross-sectional market-data schema.