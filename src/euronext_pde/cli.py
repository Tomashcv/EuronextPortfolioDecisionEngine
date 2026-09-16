from __future__ import annotations

import argparse
import platform
import sys

from .config import load_config
from .paths import ProjectPaths


def doctor() -> int:
    paths = ProjectPaths.discover()
    config = load_config()

    print("=" * 72)
    print("EURONEXT PORTFOLIO DECISION ENGINE — DOCTOR")
    print("=" * 72)

    print(f"Python:        {sys.version.split()[0]}")
    print(f"OS:            {platform.system()} {platform.release()}")
    print(f"Project root:  {paths.root}")
    print(f"Config:        {config['name']}")
    print(f"Cadence:       {config['cadence']}")

    print()
    print("Paths:")

    for name in (
        "data",
        "raw",
        "snapshots",
        "processed",
        "outputs",
        "research",
    ):
        path = getattr(paths, name)
        print(f"  {name:12s} {path}")

    print()
    print("V1 scope:")

    for key, enabled in config["scope"].items():
        print(f"  {key:20s} {enabled}")

    print()
    print("STATUS: PASS")

    return 0


def weekly() -> int:
    print(
        "Weekly pipeline skeleton is installed. V1A universe/data ingestion is the next milestone."
    )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="epde",
        description="Euronext Portfolio Decision Engine",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "doctor",
        help="Validate the local project environment.",
    )

    subparsers.add_parser(
        "weekly",
        help="Run the weekly decision pipeline.",
    )

    args = parser.parse_args()

    if args.command == "doctor":
        return doctor()

    if args.command == "weekly":
        return weekly()

    parser.print_help()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
