from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import ProjectPaths


def load_config(path: Path | None = None) -> dict[str, Any]:
    paths = ProjectPaths.discover()

    config_path = path or paths.config / "v1.yaml"

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise TypeError(f"Invalid config: {config_path}")

    return config
