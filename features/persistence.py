"""
features/persistence.py
------------------------
Save and load feature datasets.

Supports two backends:
  - Parquet files (preferred for large datasets, used by model training)
  - SQLAlchemy DB (match_features table; used for API serving and incremental updates)

Both are write-idempotent — re-running build_features overwrites existing rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session

from db.models.match_features import MatchFeature

# ---------------------------------------------------------------------------
# Parquet persistence
# ---------------------------------------------------------------------------

def save_parquet(df: pd.DataFrame, output_dir: Path, season: int | None = None) -> Path:
    """
    Save a feature DataFrame to a timestamped parquet file.

    Args:
        df:         Feature DataFrame (one row per match).
        output_dir: Directory to write to (created if absent).
        season:     Optional season tag appended to the filename.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    season_tag = f"_{season}" if season else ""
    path = output_dir / f"features{season_tag}_{ts}.parquet"
    df.to_parquet(path, index=False)
    logger.info(f"persistence: saved {len(df)} rows to {path}")
    return path


def load_latest_parquet(output_dir: Path, season: int | None = None) -> pd.DataFrame | None:
    """
    Load the most recently written parquet file from output_dir.

    Args:
        output_dir: Directory to search.
        season:     If provided, only consider files with a matching season tag.

    Returns:
        DataFrame or None if no files found.
    """
    pattern = f"features_{season}_*.parquet" if season else "features*.parquet"
    files = sorted(output_dir.glob(pattern))
    if not files:
        logger.warning(f"persistence: no parquet files found in {output_dir}")
        return None
    latest = files[-1]
    df = pd.read_parquet(latest)
    logger.info(f"persistence: loaded {len(df)} rows from {latest}")
    return df


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def upsert_match_features(db: Session, rows: list[dict]) -> tuple[int, int]:
    """
    Upsert feature rows into the match_features table.

    One row per match. If a row already exists for a match_id it is fully
    overwritten (feature recomputation is idempotent).

    Args:
        db:   SQLAlchemy session (caller commits).
        rows: List of dicts, each containing at minimum 'match_id' and all
              feature columns. Extra keys are silently ignored.

    Returns:
        (inserted_count, updated_count)
    """
    inserted = 0
    updated = 0

    # Build set of valid ORM column names (exclude id, relationships)
    _COLUMNS: frozenset[str] = frozenset(
        c.key for c in MatchFeature.__table__.columns if c.key != "id"
    )

    for row in rows:
        match_id = row["match_id"]
        kwargs = {k: v for k, v in row.items() if k in _COLUMNS}

        existing = (
            db.query(MatchFeature)
            .filter(MatchFeature.match_id == match_id)
            .first()
        )

        if existing is None:
            db.add(MatchFeature(**kwargs))
            inserted += 1
        else:
            for k, v in kwargs.items():
                if k not in ("match_id", "created_at"):
                    setattr(existing, k, v)
            updated += 1

    logger.debug(
        f"persistence: upserted match_features — "
        f"{inserted} inserted, {updated} updated."
    )
    return inserted, updated
