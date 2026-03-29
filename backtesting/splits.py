"""
backtesting/splits.py
----------------------
Time-based train/test split utilities.

All splits are strictly temporal — test data is always in the future relative
to all training data. Random shuffles are never used.

Splits are season-granular: AFL seasons form natural, non-overlapping annual
boundaries that are clean for walk-forward evaluation.

Two modes are supported:

  expanding_window_splits:
    Training set grows by one season each fold. This is the recommended mode
    for backtesting because it uses all available prior information.

    Fold 0: train=[s1..sK],   test=[sK+1]
    Fold 1: train=[s1..sK+1], test=[sK+2]
    ...

  rolling_window_splits:
    Training set is a fixed number of seasons that shifts forward each fold.
    Useful for assessing whether older data helps or hurts.

    Fold 0: train=[s1..sK],      test=[sK+1]
    Fold 1: train=[s2..sK+1],    test=[sK+2]
    ...

Leakage policy:
  Every split pair is validated: max(train.match_time) must be strictly less
  than min(test.match_time). Raises LeakageError on violation.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger


class LeakageError(ValueError):
    """Raised when training data is not strictly before test data in time."""


def expanding_window_splits(
    df: pd.DataFrame,
    min_train_seasons: int = 2,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Generate expanding-window (train, test) folds by season.

    Each fold tests one season, with all prior seasons as training data.

    Args:
        df:                Feature DataFrame. Must contain 'season' and 'match_time' columns.
        min_train_seasons: Minimum number of seasons required in the training set
                           before the first test fold is produced.

    Returns:
        List of (train_df, test_df) pairs in chronological order.
        Empty list if there are not enough seasons for even one fold.
    """
    seasons = sorted(df["season"].dropna().unique())
    if len(seasons) < min_train_seasons + 1:
        logger.warning(
            f"splits: only {len(seasons)} seasons available; "
            f"need at least {min_train_seasons + 1} for expanding-window splits."
        )
        return []

    splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for test_idx in range(min_train_seasons, len(seasons)):
        train_seasons = seasons[:test_idx]
        test_season = seasons[test_idx]

        train_df = df[df["season"].isin(train_seasons)].copy()
        test_df = df[df["season"] == test_season].copy()
        fold_label = str(test_season)

        _assert_no_leakage(train_df, test_df, fold_label)
        splits.append((train_df, test_df))
        logger.debug(
            f"splits: expanding fold {fold_label} — "
            f"train={len(train_df)} rows ({train_seasons[0]}–{train_seasons[-1]}), "
            f"test={len(test_df)} rows"
        )

    return splits


def rolling_window_splits(
    df: pd.DataFrame,
    train_seasons: int = 3,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Generate rolling-window (train, test) folds by season.

    Each fold tests one season, with a fixed number of prior seasons as
    training data.

    Args:
        df:             Feature DataFrame. Must contain 'season' and 'match_time' columns.
        train_seasons:  Number of seasons to include in each training window.

    Returns:
        List of (train_df, test_df) pairs in chronological order.
        Empty list if there are not enough seasons.
    """
    seasons = sorted(df["season"].dropna().unique())
    if len(seasons) < train_seasons + 1:
        logger.warning(
            f"splits: only {len(seasons)} seasons available; "
            f"need at least {train_seasons + 1} for rolling-window splits."
        )
        return []

    splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for test_idx in range(train_seasons, len(seasons)):
        window_start = test_idx - train_seasons
        train_season_slice = seasons[window_start:test_idx]
        test_season = seasons[test_idx]

        train_df = df[df["season"].isin(train_season_slice)].copy()
        test_df = df[df["season"] == test_season].copy()
        fold_label = str(test_season)

        _assert_no_leakage(train_df, test_df, fold_label)
        splits.append((train_df, test_df))
        logger.debug(
            f"splits: rolling fold {fold_label} — "
            f"train={len(train_df)} rows ({train_season_slice[0]}–{train_season_slice[-1]}), "
            f"test={len(test_df)} rows"
        )

    return splits


def check_temporal_order(df: pd.DataFrame) -> None:
    """
    Validate that a DataFrame is sorted chronologically by match_time.

    Logs a warning (does not raise) if rows are out of order.
    Rows with null match_time are excluded from the check.

    Args:
        df: Feature DataFrame with a 'match_time' column.
    """
    timed = df["match_time"].dropna()
    if timed.empty:
        return
    if not timed.is_monotonic_increasing:
        logger.warning(
            "splits: DataFrame is not sorted chronologically by match_time. "
            "Ensure the feature dataset is ordered before splitting."
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _assert_no_leakage(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    fold_label: str,
) -> None:
    """
    Assert that no training data is newer than the earliest test data.

    Uses match_time for the comparison; rows without match_time are ignored.

    Raises:
        LeakageError: If any training timestamp >= any test timestamp.
    """
    train_times = train_df["match_time"].dropna()
    test_times = test_df["match_time"].dropna()

    if train_times.empty or test_times.empty:
        return  # cannot check without timestamps

    train_max = train_times.max()
    test_min = test_times.min()

    if train_max >= test_min:
        raise LeakageError(
            f"Leakage detected in fold {fold_label!r}: "
            f"train max_time={train_max} >= test min_time={test_min}. "
            "This indicates training and test data overlap in time."
        )
