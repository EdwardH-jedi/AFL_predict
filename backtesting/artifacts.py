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
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from backtesting.bootstrap import BootstrapCI, bootstrap_metrics, format_ci


def _json_safe(value):
    """Recursively replace non-finite floats with None so output is valid JSON.

    Metrics are NaN whenever a fold produced no settled matches or no bets (see
    backtesting.metrics), and `float("nan")` has no JSON representation. null is
    the honest encoding of "not computed".
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


ARTIFACT_SCHEMA_VERSION = 2

# Probabilities are stored to 6 decimal places. Well beyond what a 10-bin ECE or
# a Brier score resolves, and it keeps the artifact small enough to commit.
_PROB_DP = 6


def _to_columnar(rows: list[dict]) -> dict[str, list]:
    """Row-oriented -> dict of equal-length columns."""
    if not rows:
        return {}
    keys = list(rows[0])
    out: dict[str, list] = {k: [r.get(k) for r in rows] for k in keys}
    if "y_prob" in out:
        out["y_prob"] = [
            (round(v, _PROB_DP) if v is not None else None) for v in out["y_prob"]
        ]
    return out


def _from_columnar(payload) -> list[dict]:
    """Columnar -> row-oriented. Tolerates an already row-oriented payload."""
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    keys = list(payload)
    n = len(payload[keys[0]])
    return [{k: payload[k][i] for k in keys} for i in range(n)]


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
    # Match-level predictions: one row per (model, match). Makes pooled,
    # non-decomposable metrics (ECE) independently re-derivable from the
    # artifact rather than having to be taken on trust.
    #
    # Held row-oriented in memory but serialised columnar (dict of equal-length
    # lists). Repeating six keys across ~8.5k rows costs about a megabyte of
    # duplicated field names for no information; columnar is ~4x smaller and
    # loads straight into a DataFrame.
    predictions: list[dict] = field(default_factory=list)
    # Reproducibility manifest — code, input, runtime and evaluation provenance.
    provenance: dict = field(default_factory=dict)

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
            # allow_nan=False: Python's default emits bare NaN/Infinity, which is
            # not valid JSON and is rejected by strict parsers. _json_safe maps
            # every non-finite metric to null first, so this never raises.
            json.dump(
                _json_safe(self.to_dict()),
                f,
                indent=2,
                default=str,
                allow_nan=False,
            )
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
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "run_at": self.run_at,
            "mode": self.mode,
            "min_train_seasons": self.min_train_seasons,
            "n_folds": self.n_folds,
            "models_evaluated": self.models_evaluated,
            "provenance": self.provenance,
            "window_results": self.window_results,
            "aggregate_metrics": self.aggregate_metrics,
            "assumptions": self.assumptions,
            "bootstrap_cis": self.bootstrap_cis,
            "predictions": _to_columnar(self.predictions),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> BacktestResult:
        """Rehydrate an artifact, refusing schema versions we cannot read.

        Schema v1 artifacts predate match-level predictions and the provenance
        manifest, and reported a single ambiguous `ece` key that was in fact
        season-weighted. They cannot be silently upgraded — the pooled figure is
        not recoverable from v1 data — so loading one is an explicit error
        rather than a partial read.
        """
        version = payload.get("artifact_schema_version", 1)
        if version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported artifact_schema_version {version!r}; this build reads "
                f"v{ARTIFACT_SCHEMA_VERSION}. v1 artifacts carry a season-weighted "
                "'ece' with no match-level predictions, so pooled calibration cannot "
                "be recovered from them — regenerate the artifact instead."
            )
        known = {
            "run_id", "run_at", "mode", "min_train_seasons", "n_folds",
            "models_evaluated", "window_results", "aggregate_metrics",
            "assumptions", "bootstrap_cis", "predictions", "provenance",
        }
        kwargs = {k: v for k, v in payload.items() if k in known}
        kwargs["predictions"] = _from_columnar(payload.get("predictions"))
        return cls(**kwargs)

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
