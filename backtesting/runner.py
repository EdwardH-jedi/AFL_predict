"""
backtesting/runner.py
----------------------
Walk-forward backtest runner.

Orchestrates the full backtest pipeline for one or more models:
  1. Split the feature dataset into temporal folds.
  2. For each fold:
     a. Validate no leakage (training strictly precedes testing in time).
     b. Fit each model on the training set (settled matches only).
     c. Predict win probabilities on the test set.
     d. Simulate paper-trade recommendations.
     e. Settle simulated bets using actual outcomes.
     f. Compute all metrics.
  3. Aggregate per-fold metrics across folds.
  4. Return a BacktestResult.

Leakage policy (enforced, not advisory):
  - Training set: all seasons with index < test season index.
  - The split assertion in backtesting.splits checks max(train.match_time) < min(test.match_time).
  - Models are fitted on settled training matches (home_win is not None).
  - Predictions on test matches use only pre-match features (enforced by the feature extractor).

Assumptions logged at run time:
  - All feature values were computed strictly pre-match (EloExtractor, FormExtractor).
  - Bookmaker odds features use snapshot_time < match_time (enforced by BookmakerExtractor).
  - The feature DataFrame is sorted chronologically before splitting.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from backtesting.artifacts import BacktestResult
from backtesting.metrics import WindowMetrics, aggregate_metrics, compute_metrics
from backtesting.simulation import settle_bets, simulate_recommendations
from backtesting.splits import (
    check_temporal_order,
    expanding_window_splits,
    rolling_window_splits,
)
from models.base_model import BaseModel

# Columns required in the feature DataFrame
_REQUIRED_COLS = {"match_id", "season", "match_time", "home_win"}

# Columns needed for recommendation simulation
_SIM_FEATURE_COLS = {
    "match_id",
    "bm_home_implied_prob",
    "bm_away_implied_prob",
    "bm_home_odds",
    "bm_away_odds",
}


class BacktestRunner:
    """
    Walk-forward backtest orchestrator.

    Args:
        mode:               'expanding' (recommended) or 'rolling'.
        min_train_seasons:  Minimum seasons of training data before first fold
                            (expanding mode) or exact training window size (rolling mode).
        edge_threshold:     Minimum edge required to recommend a bet.
        max_kelly_fraction: Hard cap on Kelly stake fraction.
    """

    def __init__(
        self,
        mode: str = "expanding",
        min_train_seasons: int = 2,
        edge_threshold: float = 0.03,
        max_kelly_fraction: float = 0.05,
    ) -> None:
        if mode not in ("expanding", "rolling"):
            raise ValueError(f"BacktestRunner: mode must be 'expanding' or 'rolling', got {mode!r}")
        self.mode = mode
        self.min_train_seasons = min_train_seasons
        self.edge_threshold = edge_threshold
        self.max_kelly_fraction = max_kelly_fraction

    def run(
        self,
        df: pd.DataFrame,
        models: list[BaseModel],
    ) -> BacktestResult:
        """
        Execute the full backtest for all models.

        Args:
            df:     Feature DataFrame. Must contain all columns in _REQUIRED_COLS
                    plus feature columns consumed by the models.
                    Must be sorted chronologically by match_time (ascending).
            models: List of BaseModel instances to evaluate.

        Returns:
            BacktestResult with per-fold and aggregate metrics for all models.
        """
        _validate_dataframe(df)
        check_temporal_order(df)

        result = BacktestResult.new(self.mode, self.min_train_seasons)
        result.assumptions = _ASSUMPTIONS
        result.models_evaluated = [m.name for m in models]

        logger.info(
            f"BacktestRunner: starting {self.mode}-window backtest "
            f"(min_train_seasons={self.min_train_seasons}, "
            f"edge_threshold={self.edge_threshold}, "
            f"models={result.models_evaluated})"
        )

        # Build temporal splits
        if self.mode == "expanding":
            splits = expanding_window_splits(df, min_train_seasons=self.min_train_seasons)
        else:
            splits = rolling_window_splits(df, train_seasons=self.min_train_seasons)

        if not splits:
            logger.warning("BacktestRunner: no folds generated — insufficient data.")
            return result

        result.n_folds = len(splits)

        # Per-model accumulator for window-level results
        model_window_results: dict[str, list[WindowMetrics]] = {m.name: [] for m in models}
        # Match-level predictions, retained so pooled (non-decomposable) metrics
        # such as ECE can be computed over all folds at once and independently
        # re-derived from the saved artifact.
        prediction_rows: list[dict] = []

        for fold_idx, (train_df, test_df) in enumerate(splits):
            fold_label = _fold_label(test_df)
            logger.info(
                f"BacktestRunner: fold {fold_idx + 1}/{len(splits)} — {fold_label} "
                f"(train={len(train_df)}, test={len(test_df)})"
            )

            for model in models:
                wm, fold_rows = self._run_fold(model, train_df, test_df, fold_label)
                model_window_results[model.name].append(wm)
                result.window_results.append(wm.to_dict())
                prediction_rows.extend(fold_rows)

        result.predictions = prediction_rows
        preds_df = pd.DataFrame(prediction_rows)

        # Aggregate per-model, passing that model's pooled predictions so
        # pooled_ece is computed over every fold at once rather than averaged
        # from per-season values (ECE is not decomposable).
        for model in models:
            pooled = (
                preds_df[preds_df["model"] == model.name]
                if not preds_df.empty
                else None
            )
            agg = aggregate_metrics(model_window_results[model.name], pooled_predictions=pooled)
            # Record the ensemble's per-fold composition for auditability (§14).
            comps = getattr(model, "fold_compositions", None)
            if comps:
                agg["fold_compositions"] = comps
            result.aggregate_metrics[model.name] = agg

        result.print_summary()
        return result

    def _run_fold(
        self,
        model: BaseModel,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        fold_label: str,
    ) -> tuple[WindowMetrics, list[dict]]:
        """Run one (train, test) fold for one model.

        Returns the fold's WindowMetrics plus one row per prediction, so pooled
        metrics can be computed across folds and audited from the artifact.
        """
        # Training requires settled matches only
        train_settled = train_df[train_df["home_win"].notna()].copy()
        if len(train_settled) < 10:
            logger.warning(
                f"[{model.name}] fold {fold_label}: only {len(train_settled)} "
                "settled training matches — model may be unreliable."
            )

        y_train = train_settled["home_win"].astype(int)
        X_train = train_settled.drop(columns=["home_win"])

        try:
            model.fit(X_train, y_train)
        except Exception as exc:
            logger.error(f"[{model.name}] fold {fold_label}: fit() failed — {exc}")
            return _empty_metrics(model.name, fold_label, len(test_df)), []

        # Predict on the full test set (model handles its own NaN logic)
        try:
            preds_df = model.predict_proba(test_df.drop(columns=["home_win"], errors="ignore"))
        except Exception as exc:
            logger.error(f"[{model.name}] fold {fold_label}: predict_proba() failed — {exc}")
            return _empty_metrics(model.name, fold_label, len(test_df)), []

        # Align actuals to predictions
        actuals = (
            test_df.set_index("match_id")["home_win"]
            .reindex(preds_df["match_id"])
        )

        # Recommendation simulation
        sim_features = _sim_features(test_df)
        try:
            bets = simulate_recommendations(
                preds_df,
                sim_features,
                edge_threshold=self.edge_threshold,
                max_kelly_fraction=self.max_kelly_fraction,
            )
            # Settle using actual outcomes
            result_map = {
                int(mid): (int(hw) if pd.notna(hw) else None)
                for mid, hw in zip(test_df["match_id"], test_df["home_win"])
            }
            bets = settle_bets(bets, actuals, match_id_to_result=result_map)
        except Exception as exc:
            logger.warning(
                f"[{model.name}] fold {fold_label}: simulation failed — {exc}. "
                "Decision metrics will be empty."
            )
            bets = pd.DataFrame()

        wm = compute_metrics(
            model_name=model.name,
            fold_label=fold_label,
            predictions_df=preds_df,
            actuals=actuals,
            simulated_bets=bets if not bets.empty else None,
        )
        logger.info(
            f"[{model.name}] fold={fold_label} "
            f"brier={wm.brier_score} ll={wm.log_loss} acc={wm.accuracy} "
            f"bets={wm.n_bets} roi={wm.roi}"
        )

        # One auditable row per prediction. `settled` marks rows that carry an
        # outcome and therefore contribute to pooled metrics; unsettled rows are
        # kept so the artifact records what was predicted, not only what scored.
        season = int(test_df["season"].iloc[0]) if len(test_df) else None
        fold_rows = [
            {
                "model": model.name,
                "fold_label": fold_label,
                "season": season,
                "match_id": int(mid),
                "y_prob": round(float(prob), 8),
                "y_true": (int(actual) if pd.notna(actual) else None),
                "settled": bool(pd.notna(actual)),
            }
            for mid, prob, actual in zip(
                preds_df["match_id"], preds_df["home_win_prob"], actuals.values
            )
        ]
        return wm, fold_rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ASSUMPTIONS: list[str] = [
    "All feature values are pre-match "
    "(EloExtractor, FormExtractor, BookmakerExtractor enforce this).",
    "Bookmaker odds features use snapshot_time < match_time.",
    "No draws are included in the target variable — home_win=None for draws.",
    "Decimal odds are fixed at the pre-match snapshot value (no in-play movement modelled).",
    "Kelly fractions are full Kelly, capped at max_kelly_fraction.",
    "One recommended bet per match at most (highest-edge side chosen).",
    "Brier score baseline for uninformative model: 0.25 (coin-flip).",
]


def _validate_dataframe(df: pd.DataFrame) -> None:
    """Raise ValueError if required columns are missing."""
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"BacktestRunner: feature DataFrame missing required columns {missing}. "
            "Ensure build_features has been run."
        )


def _fold_label(test_df: pd.DataFrame) -> str:
    """Return a human-readable label for the test window."""
    seasons = sorted(test_df["season"].dropna().unique())
    if not seasons:
        return "unknown"
    return str(int(seasons[0])) if len(seasons) == 1 else f"{int(seasons[0])}–{int(seasons[-1])}"


def _sim_features(test_df: pd.DataFrame) -> pd.DataFrame:
    """Extract bookmaker simulation columns from test_df, returning sensible defaults."""
    available = [c for c in _SIM_FEATURE_COLS if c in test_df.columns]
    missing = _SIM_FEATURE_COLS - set(available)
    if missing:
        logger.debug(
            f"simulation: test_df missing {missing} — affected matches will be no-bet."
        )
        # Add missing columns as NaN so simulate_recommendations can handle them
        df = test_df[available].copy()
        for col in missing:
            df[col] = float("nan")
        return df
    return test_df[list(_SIM_FEATURE_COLS)].copy()


def _empty_metrics(model_name: str, fold_label: str, n_matches: int) -> WindowMetrics:
    """Return a WindowMetrics with all NaN values (used when a step fails)."""
    import math
    return WindowMetrics(
        model_name=model_name,
        fold_label=fold_label,
        n_matches=n_matches,
        n_settled=0,
        brier_score=math.nan,
        log_loss=math.nan,
        accuracy=math.nan,
        ece=math.nan,
        n_bets=0,
        n_no_bet=0,
        hit_rate=math.nan,
        avg_edge=math.nan,
        total_staked=0.0,
        roi=math.nan,
    )
