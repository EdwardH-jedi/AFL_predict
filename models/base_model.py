"""
models/base_model.py
---------------------
Abstract base class for all prediction models.
Every model must implement fit() and predict_proba().
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd


class BaseModel(ABC):
    """
    All AFL prediction models inherit from this.

    Convention:
        - predict_proba returns a DataFrame with columns [match_id, home_win_prob, away_win_prob]
        - Probabilities must sum to 1.0 per row
        - Models are serialised to / loaded from the artifacts directory
    """

    name: str = "base"
    version: str = "0.1"

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train the model on feature matrix X and target vector y."""

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Return predicted probabilities for each match.

        Args:
            X: Feature DataFrame — must contain a 'match_id' column.

        Returns:
            DataFrame with columns: match_id, home_win_prob, away_win_prob
        """

    def save(self, artifacts_dir: str | Path) -> Path:
        """Persist model to disk. Default: raise NotImplementedError."""
        raise NotImplementedError(f"{self.name}.save() not yet implemented.")

    def load(self, artifacts_dir: str | Path) -> None:
        """Load model from disk. Default: raise NotImplementedError."""
        raise NotImplementedError(f"{self.name}.load() not yet implemented.")

    def metadata(self) -> dict[str, Any]:
        """Return model metadata dict for storage in model_runs table."""
        return {"name": self.name, "version": self.version}
