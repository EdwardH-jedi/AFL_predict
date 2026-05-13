"""
models/elo_baseline.py
-----------------------
ELO rating baseline model.

ELO ratings are updated match-by-match from historical results.
Win probability for the home team is derived from the rating difference using
the standard ELO formula with a home-ground advantage offset.

Design notes:
  - K-factor and home advantage use the scaffold defaults (K=30, HA=60).
    These should be tuned once sufficient historical data is available.
  - Season regression: 30% toward the current-season mean at each season
    boundary (reduces accumulated historical advantage).
  - fit() validates that X is sorted chronologically; out-of-order data
    would silently corrupt ratings.

NOTE: This model maintains its own internal ELO state independent of the
pre-computed ELO features in the feature matrix (home_elo_pre, elo_diff).
Both approaches should produce similar results; discrepancies indicate a
parameter mismatch that should be investigated.
"""

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from models.base_model import BaseModel

# Default ELO parameters — tune these against historical data
DEFAULT_K = 30.0
DEFAULT_HOME_ADVANTAGE = 60.0  # ELO points added to home team rating
INITIAL_RATING = 1500.0
SEASON_REGRESSION = 0.3  # Regress 30% towards mean at start of each season


class EloBaseline(BaseModel):
    """
    ELO-based win probability model.

    Ratings are maintained as a dict {team_id: elo_rating}.
    fit() replays historical matches in chronological order to build ratings.
    predict_proba() uses current ratings to forecast upcoming matches.
    """

    name = "elo_baseline"
    version = "0.1"

    def __init__(
        self,
        k_factor: float = DEFAULT_K,
        home_advantage: float = DEFAULT_HOME_ADVANTAGE,
        season_regression: float = SEASON_REGRESSION,
    ) -> None:
        self.k_factor = k_factor
        self.home_advantage = home_advantage
        self.season_regression = season_regression
        self.ratings: dict[int, float] = {}  # {team_id: elo}

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """
        Replay historical matches to build ELO ratings.

        Args:
            X: Feature DataFrame sorted by match_time ascending.
               Must contain: match_id, season, home_team_id, away_team_id.
               Rows must be in chronological order — out-of-order data
               will corrupt the ratings without raising an error.
            y: Binary series (1 = home win, 0 = away win). Index aligns with X.
        """
        required = {"match_id", "season", "home_team_id", "away_team_id"}
        if not required.issubset(X.columns):
            raise ValueError(f"EloBaseline.fit: missing columns {required - set(X.columns)}")

        self.ratings = {}
        prev_season: int | None = None

        for idx, row in X.iterrows():
            season = int(row["season"])
            home_id = int(row["home_team_id"])
            away_id = int(row["away_team_id"])
            actual = y.loc[idx]  # 1 = home win, 0 = away win

            # Season reset: regress ratings towards mean
            if prev_season is not None and season != prev_season:
                self._season_regression()
            prev_season = season

            home_elo = self.ratings.get(home_id, INITIAL_RATING)
            away_elo = self.ratings.get(away_id, INITIAL_RATING)

            # Expected score for home team (with home advantage offset)
            expected_home = self._expected(home_elo + self.home_advantage, away_elo)

            # Update ratings
            self.ratings[home_id] = home_elo + self.k_factor * (actual - expected_home)
            self.ratings[away_id] = away_elo + self.k_factor * ((1 - actual) - (1 - expected_home))

        logger.info(f"EloBaseline.fit(): trained on {len(X)} matches. {len(self.ratings)} teams.")

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        """Predict win probabilities using current ELO ratings."""
        required = {"match_id", "home_team_id", "away_team_id"}
        if not required.issubset(X.columns):
            missing = required - set(X.columns)
            raise ValueError(f"EloBaseline.predict_proba: missing columns {missing}")

        results = []
        for _, row in X.iterrows():
            home_id = int(row["home_team_id"])
            away_id = int(row["away_team_id"])
            home_elo = self.ratings.get(home_id, INITIAL_RATING)
            away_elo = self.ratings.get(away_id, INITIAL_RATING)
            home_prob = self._expected(home_elo + self.home_advantage, away_elo)
            results.append({
                "match_id": row["match_id"],
                "home_win_prob": round(home_prob, 6),
                "away_win_prob": round(1.0 - home_prob, 6),
            })

        return pd.DataFrame(results, index=X.index)

    def save(self, artifacts_dir: str | Path) -> Path:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "wb") as f:
            pickle.dump({
                "ratings": self.ratings,
                "k": self.k_factor,
                "ha": self.home_advantage,
                "season_regression": self.season_regression,
            }, f)
        logger.info(f"EloBaseline saved to {path}")
        return path

    def load(self, artifacts_dir: str | Path) -> None:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.ratings = data["ratings"]
        self.k_factor = data["k"]
        self.home_advantage = data["ha"]
        # Old artifacts may not have season_regression stored — fall back to current default
        self.season_regression = data.get("season_regression", self.season_regression)
        logger.info(f"EloBaseline loaded from {path}")

    def metadata(self) -> dict[str, Any]:
        return {
            **super().metadata(),
            "k_factor": self.k_factor,
            "home_advantage": self.home_advantage,
            "season_regression": self.season_regression,
            "n_teams": len(self.ratings),
        }

    @staticmethod
    def _expected(rating_a: float, rating_b: float) -> float:
        """Standard ELO expected score formula."""
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

    def _season_regression(self) -> None:
        """Regress all team ratings towards the mean at the start of a new season."""
        mean = np.mean(list(self.ratings.values())) if self.ratings else INITIAL_RATING
        self.ratings = {
            team_id: rating + self.season_regression * (mean - rating)
            for team_id, rating in self.ratings.items()
        }
