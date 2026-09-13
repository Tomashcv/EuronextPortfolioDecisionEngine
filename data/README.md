# Data

Market data are intentionally excluded from Git.

The V1 pipeline uses three local layers:

- `raw/` — source responses exactly as acquired;
- `snapshots/` — point-in-time weekly snapshots;
- `processed/` — normalized research-ready datasets.

No script should depend on an absolute Windows or Linux path.
All paths are resolved relative to the repository root.