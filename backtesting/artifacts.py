"""
backtesting/artifacts.py
-------------------------
Backtest result output structure.

BacktestResult captures the complete output of one backtest run — all
per-fold metrics for all models — and provides serialisation (JSON) and
summary table utilities.

The result file is saved to storage/backtest_results/ with a timestamped
filename so every run is preserved and comparable.

Format on disk: plain JSON, one file per run. Human-readable and suitable
for loading into any analysis tool.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from backtesting.bootstrap import BootstrapCI, bootstrap_metrics, format_ci


@dataclass
class BacktestResult:
    """
    Complete output of one backtest run.

    Attributes:
        run_id:             UUID string, unique per run.
        run_at:             ISO-8601 UTC timestamp of when the run started.
        mode:               'expanding' or 'rolling'.
        min_train_seasons:  Minimum training seasons used (expanding mode) or
                            exact training window size (rolling mode).
        n_folds:            Number of temporal folds evaluated.
        models_evaluated:   List of model names that were run.
        window_results:     Per-fold, per-model WindowMetrics (as dicts).
        aggregate_metrics:  Per-model aggregated metrics across all folds.
        assumptions:        Free-text list of assumptions logged during the run.
    """
    run_id: str
    run_at: str
    mode: str
    min_train_seasons: int
    n_folds: int
    models_evaluated: list[str]
    window_results: list[dict] = field(default_factory=list)
    aggregate_metrics: dict[str, dict] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    # Bootstrap CIs per model — populated by compute_bootstrap_cis()
    bootstrap_cis: dict[str, dict] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Factory
    # ---------------------------------------------------------------------------

    @classmethod
    def new(cls, mode: str, min_train_seasons: int) -> BacktestResult:
        """Create a fresh BacktestResult for a new run."""
        return cls(
            run_id=str(uuid.uuid4()),
            run_at=datetime.now(tz=UTC).isoformat(),
            mode=mode,
            min_train_seasons=min_train_seasons,
            n_folds=0,
            models_evaluated=[],
        )

    # ---------------------------------------------------------------------------
    # Serialisation
    # ---------------------------------------------------------------------------

    def save(self, output_dir: Path) -> Path:
        """
        Save the result as a JSON file.

        Filename: backtest_{run_id[:8]}_{YYYYMMDDTHHMMSSZ}.json

        Args:
            output_dir: Directory to write to (created if absent).

        Returns:
            Path to the written file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        filename = f"backtest_{self.run_id[:8]}_{ts}.json"
        path = output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        logger.info(f"BacktestResult saved to {path}")
        return path

    @classmethod
    def load(cls, path: Path) -> BacktestResult:
        """Load a BacktestResult from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            run_id=data["run_id"],
            run_at=data["run_at"],
            mode=data["mode"],
            min_train_seasons=data.get("min_train_seasons", 2),
            n_folds=data["n_folds"],
            models_evaluated=data["models_evaluated"],
            window_results=data.get("window_results", []),
            aggregate_metrics=data.get("aggregate_metrics", {}),
            assumptions=data.get("assumptions", []),
            bootstrap_cis=data.get("bootstrap_cis", {}),
        )

    def compute_bootstrap_cis(
        self,
        bets_by_model: dict[str, list[dict]],
        n_iter: int = 1000,
    ) -> None:
        """
        Compute and store bootstrap CIs for each model.

        Args:
            bets_by_model: Dict of model_name → list of bet dicts.
                           Each bet dict must have keys: profit, stake_fraction, won.
            n_iter: Bootstrap iterations (default 1000).
        """
        for model_name, bets in bets_by_model.items():
            ci: BootstrapCI = bootstrap_metrics(bets, n_iter=n_iter)
            self.bootstrap_cis[model_name] = ci.to_dict()
            logger.info(f"Bootstrap CI [{model_name}]:\n{format_ci(ci)}")

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_at": self.run_at,
            "mode": self.mode,
            "min_train_seasons": self.min_train_seasons,
            "n_folds": self.n_folds,
            "models_evaluated": self.models_evaluated,
            "window_results": self.window_results,
            "aggregate_metrics": self.aggregate_metrics,
            "assumptions": self.assumptions,
            "bootstrap_cis": self.bootstrap_cis,
        }

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------

    def summary_df(self) -> pd.DataFrame:
        """
        Return a DataFrame with per-fold metrics, suitable for display or CSV export.

        Each row is one (model, fold) combination.
        """
        if not self.window_results:
            return pd.DataFrame()
        return pd.DataFrame(self.window_results)

    def aggregate_df(self) -> pd.DataFrame:
        """
        Return a DataFrame with per-model aggregate metrics, sorted by brier_score.
        """
        if not self.aggregate_metrics:
            return pd.DataFrame()
        rows = list(self.aggregate_metrics.values())
        df = pd.DataFrame(rows)
        if "brier_score" in df.columns:
            df = df.sort_values("brier_score", na_position="last").reset_index(drop=True)
        return df

    def print_summary(self) -> None:
        """Log a compact summary to the loguru logger."""
        agg = self.aggregate_df()
        if agg.empty:
            logger.info("BacktestResult: no aggregate metrics to display.")
            return

        logger.info(
            f"\nBacktest Summary — {self.run_at[:10]}  "
            f"mode={self.mode}  folds={self.n_folds}\n"
            + agg.to_string(index=False)
        )
