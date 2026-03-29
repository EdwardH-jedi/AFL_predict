"""
orchestration/jobs/build_features.py
--------------------------------------
Job: Build the pre-match feature matrix from stored match and odds data.

Pipeline:
  1. Load all matches from DB (sorted chronologically).
  2. Run ELO, form, rest-days, venue, and bookmaker extractors.
  3. Merge features into a single DataFrame.
  4. Upsert features into the match_features DB table (for API / recommendations).
  5. Save a timestamped parquet snapshot (for model training).

Run daily at ~07:30 AEST after ingest_afl and ingest_tab_odds.

CLI usage:
    python -m orchestration.jobs.build_features
    python -m orchestration.jobs.build_features --season 2025
    python -m orchestration.jobs.build_features --no-db   # parquet only
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from config.settings import get_settings
from db.models.pipeline_runs import PipelineRun
from db.session import db_session
from features.feature_builder import DatasetBuilder
from features.persistence import save_parquet, upsert_match_features

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"


def run(season: int | None = None, write_db: bool = True) -> None:
    """
    Build and persist the feature DataFrame.

    Args:
        season:   If provided, build features only for this season.
                  Historical data is still used to seed ELO/form state.
        write_db: If True (default), upsert features into the match_features
                  table in addition to writing the parquet file.
    """
    start = time.monotonic()
    logger.info(f"==> build_features: starting (season={season}, write_db={write_db})")
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    with db_session() as db:
        run_record = PipelineRun(job_name="build_features", status="running")
        db.add(run_record)
        db.flush()

        try:
            builder = DatasetBuilder(db)
            df = builder.build(season=season)

            if df.empty:
                logger.warning("build_features: empty feature DataFrame — skipping save.")
                run_record.status = "completed"
                run_record.completed_at = datetime.now(tz=timezone.utc)
                run_record.duration_seconds = round(time.monotonic() - start, 2)
                run_record.records_processed = 0
                return

            # --- Parquet snapshot (always) ---
            save_parquet(df, FEATURES_DIR, season=season)

            # --- DB upsert (optional, for API serving) ---
            if write_db:
                rows = df.to_dict(orient="records")
                inserted, updated = upsert_match_features(db, rows)
                logger.info(
                    f"build_features: match_features upsert — "
                    f"{inserted} inserted, {updated} updated."
                )

            duration = time.monotonic() - start
            run_record.status = "completed"
            run_record.completed_at = datetime.now(tz=timezone.utc)
            run_record.duration_seconds = round(duration, 2)
            run_record.records_processed = len(df)
            logger.info(
                f"==> build_features: completed in {duration:.1f}s — "
                f"{len(df)} rows."
            )

        except Exception as exc:
            run_record.status = "failed"
            run_record.error_message = str(exc)
            logger.exception("==> build_features: FAILED")
            raise


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build pre-match feature matrix from stored AFL and odds data."
    )
    p.add_argument(
        "--season", type=int, default=None,
        help="Restrict output rows to this season (default: all seasons)."
    )
    p.add_argument(
        "--no-db", action="store_true",
        help="Write parquet only; skip match_features DB upsert."
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(season=args.season, write_db=not args.no_db)
    except Exception:
        sys.exit(1)
