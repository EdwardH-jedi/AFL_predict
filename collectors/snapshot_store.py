"""
collectors/snapshot_store.py
-----------------------------
Shared helper for persisting raw API payloads to disk before any processing.

Every collector should call SnapshotStore.save() immediately after receiving
a response, before parsing or validation. This ensures the raw source data is
always available for debugging, replay, and auditing, regardless of what
happens in downstream layers.

Design notes:
  - Files are named  <label>_<UTC-timestamp>.json
  - One SnapshotStore instance per logical source (e.g. 'squiggle', 'odds_api')
  - load_latest() supports replaying the most recent snapshot without a network call
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


class SnapshotStore:
    """
    Saves and loads timestamped raw JSON snapshots for a single data source.

    Usage:
        store = SnapshotStore(base_dir="./storage/raw_snapshots", source="squiggle")
        path = store.save(payload, label="games_2025")
        payload = store.load_latest("games_2025")
    """

    def __init__(self, base_dir: str | Path, source: str) -> None:
        """
        Args:
            base_dir: Root directory for all snapshots (from settings.raw_snapshots_dir).
            source:   Sub-directory name identifying the data source (e.g. 'squiggle').
        """
        self.source = source
        self.dir = Path(base_dir) / source
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, payload: Any, label: str) -> Path:
        """
        Serialise payload to a timestamped JSON file.

        Args:
            payload: Any JSON-serialisable object (dict, list, etc.).
            label:   Descriptive prefix for the filename (e.g. 'games_2025_r3').

        Returns:
            Path to the saved file.
        """
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.dir / f"{label}_{ts}.json"
        path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        logger.debug(f"snapshot_store [{self.source}]: saved {path.name}")
        return path

    def load_latest(self, label_prefix: str) -> Any | None:
        """
        Load the most recently saved snapshot whose filename starts with label_prefix.

        Returns None if no matching file exists.
        """
        candidates = sorted(
            self.dir.glob(f"{label_prefix}_*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            logger.debug(
                f"snapshot_store [{self.source}]: no snapshot found for prefix {label_prefix!r}"
            )
            return None
        path = candidates[-1]
        logger.debug(f"snapshot_store [{self.source}]: loading {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_snapshots(self, label_prefix: str = "") -> list[Path]:
        """Return all snapshot files, optionally filtered by label prefix, newest first."""
        pattern = f"{label_prefix}*.json" if label_prefix else "*.json"
        return sorted(
            self.dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
