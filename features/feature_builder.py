"""
features/feature_builder.py
-----------------------------
DatasetBuilder — orchestrates all feature extractors into a single DataFrame.

Each match produces one row with all feature columns. The builder:
  1. Loads matches from the DB (sorted chronologically).
  2. Runs each extractor in sequence, collecting per-match feature dicts.
  3. Merges results, resolving conflicts by giving later extractors priority.
  4. Attaches the target variable (home_win).
  5. Runs dataset-level validators (null rate checks).

Leakage policy: enforced by individual extractors. The builder adds a
final leakage check per row and logs any violations.

Usage:
    builder = DatasetBuilder(db)
    df = builder.build(season=2025)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session

from db.models.matches import Match
from features.extractors.bookmaker import BookmakerExtractor
from features.extractors.elo import EloExtractor
from features.extractors.form import FormExtractor
from features.extractors.rest import RestDaysExtractor
from features.extractors.venue import VenueExtractor
from features.validators import check_leakage, check_null_rates, check_ranges


class DatasetBuilder:
    """
    Builds a flat feature DataFrame from match and odds data.

    Each row = one match. Columns = pre-match features + target variable.
    """

    def __init__(self, db: Session, form_window: int = 10) -> None:
        self._db = db
        self._form_window = form_window

    def build(self, season: int | None = None) -> pd.DataFrame:
        """
        Build the full feature dataset.

        Args:
            season: If provided, restrict to a single season. All historical
                    data is still used to initialise ELO and form state — only
                    the output rows are filtered to the requested season.

        Returns:
            DataFrame with one row per match and all feature columns.
        """
        logger.info(f"DatasetBuilder: building features (season filter={season})")

        # Load ALL matches chronologically to ensure ELO/form state is correct
        all_matches = self._load_matches_sorted()
        if not all_matches:
            logger.warning("DatasetBuilder: no matches found — returning empty DataFrame.")
            return pd.DataFrame()

        # --- Run extractors (each does a single pass over all_matches) ---
        extractors = [
            EloExtractor(),
            FormExtractor(window=self._form_window),
            RestDaysExtractor(),
            VenueExtractor(),
            BookmakerExtractor(self._db),  # requires DB; runs last
        ]

        # Start with an empty feature store per match_id
        features: dict[int, dict] = {m.id: {} for m in all_matches}

        for extractor in extractors:
            logger.debug(f"DatasetBuilder: running {extractor.name}")
            extracted = extractor.extract(all_matches)
            for match_id, row in extracted.items():
                features[match_id].update(row)

        # --- Merge with match metadata and target ---
        match_index = {m.id: m for m in all_matches}
        rows: list[dict] = []
        leakage_count = 0
        range_violation_count = 0

        for match in all_matches:
            # Apply season filter to OUTPUT rows only
            if season is not None and match.season != season:
                continue

            feat = features.get(match.id, {})
            row = {
                "match_id": match.id,
                "season": match.season,
                "round_number": match.round_number,
                "home_team_id": match.home_team_id,
                "away_team_id": match.away_team_id,
                "match_time": match.match_time,
                "is_final": match.is_final,
                "home_win": _target(match),
                **feat,
            }

            # --- Per-row validation ---
            leakage_issues = check_leakage(row, match.match_time)
            if leakage_issues:
                leakage_count += 1
                for issue in leakage_issues:
                    logger.error(f"DatasetBuilder leakage match_id={match.id}: {issue}")

            range_issues = check_ranges(row)
            if range_issues:
                range_violation_count += 1
                for issue in range_issues:
                    logger.warning(f"DatasetBuilder range match_id={match.id}: {issue}")

            rows.append(row)

        if leakage_count:
            logger.error(
                f"DatasetBuilder: {leakage_count} leakage violations detected — "
                "review extractor logic immediately."
            )

        # --- Dataset-level null rate check ---
        null_issues = check_null_rates(rows)
        for issue in null_issues:
            logger.warning(f"DatasetBuilder null rate: {issue}")

        df = pd.DataFrame(rows)
        logger.info(
            f"DatasetBuilder: built {len(df)} rows × {len(df.columns)} columns "
            f"(season={season})."
        )
        return df

    def _load_matches_sorted(self) -> list[Match]:
        """
        Load all matches sorted chronologically.

        Matches without match_time are placed at the end (NULLS LAST).
        """
        return (
            self._db.query(Match)
            .order_by(
                Match.match_time.asc().nulls_last(),
                Match.season.asc(),
                Match.round_number.asc(),
            )
            .all()
        )


# ---------------------------------------------------------------------------
# Backward-compatibility shim
# ---------------------------------------------------------------------------

class FeatureBuilder(DatasetBuilder):
    """
    Alias for DatasetBuilder retained for backward compatibility with
    orchestration/jobs/build_features.py. New code should use DatasetBuilder.
    """
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _target(match: Match) -> int | None:
    """Return 1 if home team won, 0 if away team won, None otherwise."""
    if match.result == "home":
        return 1
    if match.result == "away":
        return 0
    return None  # draw or not yet played
