from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository root without relying on OS-specific paths."""

    current = (start or Path.cwd()).resolve()

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    fallback = Path(__file__).resolve().parents[2]

    if (fallback / "pyproject.toml").is_file():
        return fallback

    raise RuntimeError("Could not locate project root.")


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config: Path
    data: Path
    raw: Path
    snapshots: Path
    processed: Path
    outputs: Path
    research: Path

    @classmethod
    def discover(cls) -> ProjectPaths:
        root = find_project_root()

        return cls(
            root=root,
            config=root / "config",
            data=root / "data",
            raw=root / "data" / "raw",
            snapshots=root / "data" / "snapshots",
            processed=root / "data" / "processed",
            outputs=root / "outputs",
            research=root / "research",
        )