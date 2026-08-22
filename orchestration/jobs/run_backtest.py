"""
orchestration/jobs/run_backtest.py
------------------------------------
Job: Run the full walk-forward backtest for all baseline models.

Pipeline:
  1. Load the latest features parquet.
  2. Run expanding-window (or rolling-window) backtests.
  3. Compute per-fold and aggregate metrics.
  4. Save a JSON result artifact.
  5. Print a summary table.

All splits are strictly temporal — test data is always in the future relative
to all training data. See docs/backtesting.md for the full methodology.

CLI usage:
    python -m orchestration.jobs.run_backtest
    python -m orchestration.jobs.run_backtest --mode rolling --min-train-seasons 3
    python -m orchestration.jobs.run_backtest --edge-threshold 0.05

    # The form used for every number in docs/RESULTS.md:
    python -m orchestration.jobs.run_backtest --min-season 2017 --max-season 2025 --untuned
"""

import argparse
import json
import sys
import time
from pathlib import Path

from loguru import logger

from backtesting.runner import BacktestRunner
from config.settings import get_settings
from models.bookmaker_baseline import BookmakerBaseline
from models.elo_baseline import EloBaseline
from models.ensemble import TrainableEnsemble
from models.logistic_baseline import LogisticBaseline
from models.poisson_model import PoissonModel
from models.xgboost_model import XGBoostModel

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"
BACKTEST_DIR = Path(settings.raw_snapshots_dir) / "backtest_results"


def run(
    mode: str = "expanding",
    min_train_seasons: int = 2,
    edge_threshold: float = 0.03,
    max_kelly_fraction: float | None = None,
    min_season: int | None = None,
    max_season: int | None = None,
    untuned: bool = False,
) -> None:
    """
    Run the full walk-forward backtest for all baseline models plus the ensemble.

    Args:
        mode:               'expanding' or 'rolling'.
        min_train_seasons:  Minimum training seasons (expanding) or
                            training window size (rolling).
        edge_threshold:     Minimum model edge to recommend a bet.
        max_kelly_fraction: Kelly cap. Defaults to settings.max_kelly_fraction.
        min_season:         Drop seasons before this year. Use it to restrict the
                            run to seasons with bookmaker-odds coverage — folds
                            without odds cannot produce bookmaker-baseline or
                            decision (ROI/hit-rate) metrics, and mixing them in
                            makes the aggregate averages incomparable.
        max_season:         Drop seasons after this year (e.g. exclude an
                            in-progress season with mostly unsettled matches).
        untuned:            Ignore storage/model_artifacts/*_best_params.json and
                            use each model class's own constructor defaults.

                            Use this for any result you intend to publish. The
                            tuners (backtesting/elo_tuner.py, xgb_tuner.py) search
                            over these same walk-forward folds, so parameters they
                            selected are contaminated by the test data — reporting
                            metrics produced with them overstates Elo and XGBoost.
                            Note that the non-untuned fallback literals below are
                            ALSO tuner-era values (they were committed alongside
                            the tuner artifacts), so absent-file != untuned.
    """
    start = time.monotonic()
    logger.info(
        f"==> run_backtest: starting "
        f"(mode={mode}, min_train_seasons={min_train_seasons}, "
        f"edge_threshold={edge_threshold})"
    )

    if max_kelly_fraction is None:
        max_kelly_fraction = settings.max_kelly_fraction

    df = _load_latest_features()
    if df is None or df.empty:
        logger.error("run_backtest: no feature data. Run build_features first.")
        return

    df = _filter_seasons(df, min_season=min_season, max_season=max_season)
    if df.empty:
        logger.error(
            f"run_backtest: no rows left after season filter "
            f"(min_season={min_season}, max_season={max_season})."
        )
        return

    # Hyperparameters. `untuned` means the model classes' own constructor
    # defaults, with nothing tuner-derived anywhere in the chain.
    artifacts_dir = Path(settings.model_artifacts_dir)
    if untuned:
        logger.info(
            "run_backtest: --untuned — ignoring *_best_params.json and using model "
            "constructor defaults, so no value selected on these folds can leak in."
        )
        elo_params = None
        xgb_params = None
    else:
        elo_params = _load_json_params(
            artifacts_dir / "elo_best_params.json",
            defaults={"k_factor": 24.0, "home_advantage": 50.0, "season_regression": 0.70},
        )
        xgb_params = _load_json_params(
            artifacts_dir / "xgb_best_params.json",
            defaults={"max_depth": 3, "learning_rate": 0.1, "n_estimators": 200, "subsample": 0.8},
        )
        logger.warning(
            "run_backtest: using tuned hyperparameters. The tuners search these same "
            "folds — do not publish these metrics as leakage-free. Use --untuned."
        )

    models = [
        BookmakerBaseline(),
        _make_elo(elo_params),
        LogisticBaseline(),
        _make_xgb(xgb_params),
        PoissonModel(),
    ]

    # Ensemble of the four forecasting models, weighted from the single source
    # of truth (Settings.ensemble_weights) so the benchmarked blend is the
    # blend production ships. Components are fresh instances: BacktestRunner
    # refits every model per fold, and sharing instances with the standalone
    # entries above would mean each fold's fit silently reused the other's state.
    ensemble = _build_ensemble(elo_params, xgb_params)
    if ensemble is not None:
        models.append(ensemble)

    runner = BacktestRunner(
        mode=mode,
        min_train_seasons=min_train_seasons,
        edge_threshold=edge_threshold,
        max_kelly_fraction=max_kelly_fraction,
    )

    result = runner.run(df, models)

    # Save artifact
    path = result.save(BACKTEST_DIR)

    duration = time.monotonic() - start
    logger.info(f"==> run_backtest: completed in {duration:.1f}s — results at {path}")

    # Print aggregate summary
    agg = result.aggregate_df()
    if not agg.empty:
        _key_cols = [
            "model_name", "n_folds", "n_settled_total",
            "brier_score", "log_loss", "accuracy", "ece",
            "n_bets_total", "hit_rate", "avg_edge", "roi",
        ]
        display_cols = [c for c in _key_cols if c in agg.columns]
        print("\n=== Aggregate (all seasons) ===")
        print(agg[display_cols].to_string(index=False))

    # Print per-season breakdown for the two best models
    fold_df = result.summary_df()
    if not fold_df.empty:
        _fold_cols = [
            "fold_label",
            "model_name",
            "n_settled",
            "brier_score",
            "accuracy",
            "n_bets",
            "roi",
        ]
        fold_display = [c for c in _fold_cols if c in fold_df.columns]
        # Show logistic and xgboost per-season
        best_models = ["logistic_baseline", "xgboost", "elo_baseline", "ensemble"]
        fold_subset = fold_df[fold_df["model_name"].isin(best_models)][fold_display]
        if not fold_subset.empty:
            print("\n=== Per-season breakdown (selected models) ===")
            print(fold_subset.sort_values(["fold_label", "model_name"]).to_string(index=False))


def _make_elo(params: dict | None) -> EloBaseline:
    """Elo from tuned params, or its own constructor defaults when params is None."""
    if params is None:
        return EloBaseline()
    return EloBaseline(
        k_factor=params["k_factor"],
        home_advantage=params["home_advantage"],
        season_regression=params["season_regression"],
    )


def _make_xgb(params: dict | None) -> XGBoostModel:
    """XGBoost from tuned params, or its own constructor defaults when params is None."""
    if params is None:
        return XGBoostModel()
    return XGBoostModel(
        max_depth=int(params["max_depth"]),
        learning_rate=params["learning_rate"],
        n_estimators=int(params["n_estimators"]),
        subsample=params["subsample"],
    )


def _filter_seasons(df, min_season: int | None, max_season: int | None):
    """Restrict the feature frame to a season range, logging what was dropped."""
    if min_season is None and max_season is None:
        return df
    before = len(df)
    if min_season is not None:
        df = df[df["season"] >= min_season]
    if max_season is not None:
        df = df[df["season"] <= max_season]
    seasons = sorted(int(s) for s in df["season"].unique())
    span = f"{seasons[0]}-{seasons[-1]}" if seasons else "none"
    logger.info(f"run_backtest: season filter kept {len(df)}/{before} rows (seasons {span})")
    return df.reset_index(drop=True)


def _build_ensemble(elo_params: dict | None, xgb_params: dict | None):
    """
    Build the production-weighted ensemble for evaluation.

    Weights come from Settings.ensemble_weights. Any configured component with
    no constructor here (e.g. bookmaker_baseline, which is the benchmark rather
    than a component) is reported and skipped. Returns None if fewer than two
    components remain, since a one-model 'ensemble' is just that model.
    """
    factories = {
        # Present so a deliberately non-zero ENSEMBLE_WEIGHT_BOOKMAKER_BASELINE is
        # actually evaluated. Production iterates every configured component, so
        # omitting it here would silently benchmark a different blend than ships.
        "bookmaker_baseline": BookmakerBaseline,
        "logistic_baseline": LogisticBaseline,
        "xgboost": lambda: _make_xgb(xgb_params),
        "poisson": PoissonModel,
        "elo_baseline": lambda: _make_elo(elo_params),
    }

    components = []
    for name, weight in settings.ensemble_weights.items():
        factory = factories.get(name)
        if factory is None:
            logger.warning(
                f"run_backtest: ensemble weight configured for {name!r} but that "
                "model is not a backtestable component — skipping it in the ensemble row."
            )
            continue
        components.append((factory(), weight))

    if len(components) < 2:
        logger.warning(
            "run_backtest: fewer than 2 ensemble components configured — "
            "skipping the ensemble row."
        )
        return None

    logger.info(
        "run_backtest: ensemble components "
        f"{ {m.name: round(w, 3) for m, w in components} }"
    )
    return TrainableEnsemble(components)


def _load_json_params(path: Path, defaults: dict) -> dict:
    """Load hyperparams from JSON, falling back to defaults if file missing."""
    try:
        with open(path) as f:
            params = json.load(f)
        logger.info(f"run_backtest: loaded params from {path}: {params}")
        return params
    except FileNotFoundError:
        logger.warning(f"run_backtest: {path} not found, using defaults {defaults}")
        return defaults


def _load_latest_features():
    """Load the most recently written features parquet file."""
    import pandas as pd
    files = sorted(FEATURES_DIR.glob("features*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        logger.error(f"run_backtest: no parquet files found in {FEATURES_DIR}")
        return None
    path = files[-1]
    logger.info(f"run_backtest: loading features from {path}")
    df = pd.read_parquet(path)
    logger.info(f"run_backtest: loaded {len(df)} rows × {len(df.columns)} columns")
    return df


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Walk-forward backtest for AFL prediction baseline models."
    )
    p.add_argument(
        "--mode", choices=["expanding", "rolling"], default="expanding",
        help="Split mode: expanding (all-history) or rolling (fixed window). Default: expanding."
    )
    p.add_argument(
        "--min-train-seasons", type=int, default=2,
        dest="min_train_seasons",
        help="Minimum training seasons (expanding) or window size (rolling). Default: 2."
    )
    p.add_argument(
        "--edge-threshold", type=float, default=0.03,
        dest="edge_threshold",
        help="Minimum edge (model_prob - bm_implied_prob) to recommend a bet. Default: 0.03."
    )
    p.add_argument(
        "--max-kelly", type=float, default=None,
        dest="max_kelly_fraction",
        help="Kelly fraction cap. Defaults to settings.max_kelly_fraction (0.05)."
    )
    p.add_argument(
        "--min-season", type=int, default=None, dest="min_season",
        help="Drop seasons before this year (e.g. the first season with odds coverage)."
    )
    p.add_argument(
        "--max-season", type=int, default=None, dest="max_season",
        help="Drop seasons after this year (e.g. exclude an in-progress season)."
    )
    p.add_argument(
        "--untuned", action="store_true",
        help=(
            "Ignore *_best_params.json and use model constructor defaults. Required "
            "for publishable numbers: the tuners search these same folds, so tuned "
            "parameters are contaminated by the test data."
        )
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(
            mode=args.mode,
            min_train_seasons=args.min_train_seasons,
            edge_threshold=args.edge_threshold,
            max_kelly_fraction=args.max_kelly_fraction,
            min_season=args.min_season,
            max_season=args.max_season,
            untuned=args.untuned,
        )
    except Exception:
        logger.exception("run_backtest: unhandled error")
        sys.exit(1)
