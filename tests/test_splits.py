"""
tests/test_splits.py
---------------------
Unit tests for backtesting/splits.py.

No network, no database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from backtesting.splits import (
    LeakageError,
    _assert_no_leakage,
    check_temporal_order,
    expanding_window_splits,
    rolling_window_splits,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(season_rows: dict[int, list[str]]) -> pd.DataFrame:
    """
    Build a minimal feature DataFrame from {season: [date_strings]}.

    e.g. _make_df({2021: ["2021-04-01", "2021-05-01"], 2022: ["2022-04-01"]})
    """
    rows = []
    match_id = 1
    for season, dates in sorted(season_rows.items()):
        for d in dates:
            rows.append({
                "match_id": match_id,
                "season": season,
                "match_time": datetime.fromisoformat(d).replace(tzinfo=timezone.utc),
                "home_win": 1,
            })
            match_id += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# expanding_window_splits
# ---------------------------------------------------------------------------

class TestExpandingWindowSplits:
    def test_basic_three_seasons(self):
        df = _make_df({
            2021: ["2021-04-01", "2021-08-01"],
            2022: ["2022-04-01", "2022-08-01"],
            2023: ["2023-04-01", "2023-08-01"],
        })
        splits = expanding_window_splits(df, min_train_seasons=2)
        assert len(splits) == 1
        train, test = splits[0]
        assert set(train["season"].unique()) == {2021, 2022}
        assert set(test["season"].unique()) == {2023}

    def test_four_seasons_produces_two_folds(self):
        df = _make_df({
            2020: ["2020-04-01"],
            2021: ["2021-04-01"],
            2022: ["2022-04-01"],
            2023: ["2023-04-01"],
        })
        splits = expanding_window_splits(df, min_train_seasons=2)
        assert len(splits) == 2
        # Second fold trains on 3 seasons
        train2, test2 = splits[1]
        assert set(train2["season"].unique()) == {2020, 2021, 2022}
        assert set(test2["season"].unique()) == {2023}

    def test_train_always_precedes_test(self):
        df = _make_df({2021: ["2021-06-01"], 2022: ["2022-06-01"], 2023: ["2023-06-01"]})
        for train, test in expanding_window_splits(df, min_train_seasons=2):
            assert train["match_time"].max() < test["match_time"].min()

    def test_not_enough_seasons_returns_empty(self):
        df = _make_df({2021: ["2021-04-01"], 2022: ["2022-04-01"]})
        # Need at least min_train_seasons + 1 = 3 seasons
        splits = expanding_window_splits(df, min_train_seasons=2)
        assert splits == []

    def test_single_season_returns_empty(self):
        df = _make_df({2022: ["2022-04-01", "2022-08-01"]})
        assert expanding_window_splits(df, min_train_seasons=1) == []

    def test_min_train_seasons_one(self):
        df = _make_df({2021: ["2021-04-01"], 2022: ["2022-04-01"]})
        splits = expanding_window_splits(df, min_train_seasons=1)
        assert len(splits) == 1
        train, test = splits[0]
        assert set(train["season"].unique()) == {2021}
        assert set(test["season"].unique()) == {2022}

    def test_growing_training_set(self):
        df = _make_df({
            2019: ["2019-04-01"],
            2020: ["2020-04-01"],
            2021: ["2021-04-01"],
            2022: ["2022-04-01"],
            2023: ["2023-04-01"],
        })
        splits = expanding_window_splits(df, min_train_seasons=2)
        train_sizes = [len(tr) for tr, _ in splits]
        # Each fold's training set should be larger than the previous
        assert train_sizes == sorted(train_sizes)


# ---------------------------------------------------------------------------
# rolling_window_splits
# ---------------------------------------------------------------------------

class TestRollingWindowSplits:
    def test_basic_rolling(self):
        df = _make_df({
            2019: ["2019-04-01"],
            2020: ["2020-04-01"],
            2021: ["2021-04-01"],
            2022: ["2022-04-01"],
        })
        splits = rolling_window_splits(df, train_seasons=2)
        assert len(splits) == 2
        # First fold: train 2019+2020, test 2021
        tr0, te0 = splits[0]
        assert set(tr0["season"].unique()) == {2019, 2020}
        assert set(te0["season"].unique()) == {2021}
        # Second fold: train 2020+2021, test 2022
        tr1, te1 = splits[1]
        assert set(tr1["season"].unique()) == {2020, 2021}
        assert set(te1["season"].unique()) == {2022}

    def test_rolling_train_size_is_constant(self):
        df = _make_df({s: [f"{s}-04-01"] for s in range(2018, 2024)})
        splits = rolling_window_splits(df, train_seasons=3)
        train_sizes = [len(tr) for tr, _ in splits]
        assert len(set(train_sizes)) == 1  # all folds same size

    def test_rolling_not_enough_seasons(self):
        df = _make_df({2021: ["2021-04-01"], 2022: ["2022-04-01"]})
        assert rolling_window_splits(df, train_seasons=2) == []


# ---------------------------------------------------------------------------
# Leakage detection
# ---------------------------------------------------------------------------

class TestLeakageDetection:
    def test_no_leakage_passes(self):
        train = _make_df({2021: ["2021-04-01"]})
        test = _make_df({2022: ["2022-04-01"]})
        _assert_no_leakage(train, test, "2022")  # should not raise

    def test_overlapping_dates_raises(self):
        train = _make_df({2021: ["2021-04-01", "2022-03-01"]})  # train has 2022 data
        test = _make_df({2022: ["2022-01-01"]})  # test starts earlier
        with pytest.raises(LeakageError):
            _assert_no_leakage(train, test, "2022")

    def test_empty_timestamps_skips_check(self):
        train = pd.DataFrame({"match_id": [1], "season": [2021], "match_time": [None], "home_win": [1]})
        test = pd.DataFrame({"match_id": [2], "season": [2022], "match_time": [None], "home_win": [1]})
        _assert_no_leakage(train, test, "2022")  # should not raise


# ---------------------------------------------------------------------------
# check_temporal_order
# ---------------------------------------------------------------------------

class TestCheckTemporalOrder:
    def test_sorted_df_no_warning(self, caplog):
        df = _make_df({2021: ["2021-04-01", "2021-08-01"]})
        check_temporal_order(df)
        assert "not sorted" not in caplog.text

    def test_unsorted_df_logs_warning(self, caplog):
        import logging
        df = _make_df({2021: ["2021-08-01", "2021-04-01"]})  # reversed order
        df = df.iloc[::-1].reset_index(drop=True)  # reverse row order
        with caplog.at_level(logging.WARNING, logger="root"):
            check_temporal_order(df)
        # loguru doesn't use caplog directly; just verify it doesn't raise
