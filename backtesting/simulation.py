"""
backtesting/simulation.py
--------------------------
Lightweight paper-trade recommendation simulation.

This module is purely computational — it takes predictions and market data
as DataFrames and returns what would have been recommended. No database
writes occur here.

The simulation models the decision rule used by generate_recommendations.py:
  1. Compute edge = model_prob - bm_implied_prob for each side.
  2. If max(home_edge, away_edge) >= edge_threshold, recommend the higher-edge side.
  3. Stake = min(kelly_fraction, max_kelly_fraction).
  4. If neither side clears the threshold: no-bet.

To measure outcomes, call settle_bets() after the match results are known.

Design notes:
  - One recommended bet per match at most (the higher-edge side).
  - If both sides have the same edge, the home side is preferred.
  - Kelly fraction is computed from model_prob, not bm_implied_prob.
  - Fractional Kelly (e.g. 0.5x) is NOT applied here — the caller should
    set max_kelly_fraction conservatively instead.

Assumptions:
  - Decimal odds are TAB closing odds (bm_home_odds / bm_away_odds).
  - Stake represents a fraction of a notional unit bankroll.
  - Odds are fixed at recommendation time (no in-play movement).
"""

from __future__ import annotations

import math

import pandas as pd
from loguru import logger


def simulate_recommendations(
    predictions_df: pd.DataFrame,
    features_df: pd.DataFrame,
    edge_threshold: float = 0.03,
    max_kelly_fraction: float = 0.05,
) -> pd.DataFrame:
    """
    Determine which matches would generate a bet recommendation and at what stake.

    Args:
        predictions_df:     DataFrame with columns: match_id, home_win_prob, away_win_prob.
        features_df:        DataFrame with columns: match_id, bm_home_implied_prob,
                            bm_away_implied_prob, bm_home_odds, bm_away_odds, match_time.
                            May contain additional columns (ignored).
        edge_threshold:     Minimum edge (model_prob - bm_implied_prob) to recommend.
                            Must be > 0. Default 0.03 (3%).
        max_kelly_fraction: Hard cap on stake fraction. Default 0.05 (5%).

    Returns:
        DataFrame of recommended bets with columns:
            match_id, side, model_prob, bm_implied_prob, bm_odds,
            edge, kelly_fraction, stake_fraction.
        One row per recommended match (never two rows for the same match).
        Matches below the edge threshold are excluded.
    """
    if edge_threshold <= 0:
        raise ValueError(f"edge_threshold must be positive, got {edge_threshold}")
    if max_kelly_fraction <= 0 or max_kelly_fraction > 1:
        raise ValueError(f"max_kelly_fraction must be in (0, 1], got {max_kelly_fraction}")

    bm_cols = {"match_id", "bm_home_implied_prob", "bm_away_implied_prob",
               "bm_home_odds", "bm_away_odds"}
    missing = bm_cols - set(features_df.columns)
    if missing:
        raise ValueError(f"simulate_recommendations: features_df missing columns {missing}")

    pred_cols = {"match_id", "home_win_prob", "away_win_prob"}
    missing_pred = pred_cols - set(predictions_df.columns)
    if missing_pred:
        raise ValueError(f"simulate_recommendations: predictions_df missing columns {missing_pred}")

    # Merge predictions with bookmaker data
    merged = predictions_df[list(pred_cols)].merge(
        features_df[list(bm_cols)],
        on="match_id",
        how="left",
    )

    rows: list[dict] = []
    n_no_bet = 0
    n_missing_odds = 0

    for _, row in merged.iterrows():
        mid = int(row["match_id"])
        home_prob = float(row["home_win_prob"])
        away_prob = float(row["away_win_prob"])

        bm_home_prob = row.get("bm_home_implied_prob")
        bm_away_prob = row.get("bm_away_implied_prob")
        bm_home_odds = row.get("bm_home_odds")
        bm_away_odds = row.get("bm_away_odds")

        # Skip if we have no bookmaker data at all
        if pd.isna(bm_home_prob) or pd.isna(bm_away_prob):
            n_missing_odds += 1
            continue
        if pd.isna(bm_home_odds) or pd.isna(bm_away_odds):
            n_missing_odds += 1
            continue

        bm_home_prob = float(bm_home_prob)
        bm_away_prob = float(bm_away_prob)
        bm_home_odds = float(bm_home_odds)
        bm_away_odds = float(bm_away_odds)

        home_edge = home_prob - bm_home_prob
        away_edge = away_prob - bm_away_prob

        # Pick the best-value side
        if home_edge >= away_edge:
            best_side = "home"
            best_edge = home_edge
            best_prob = home_prob
            best_bm_prob = bm_home_prob
            best_odds = bm_home_odds
        else:
            best_side = "away"
            best_edge = away_edge
            best_prob = away_prob
            best_bm_prob = bm_away_prob
            best_odds = bm_away_odds

        if best_edge < edge_threshold:
            n_no_bet += 1
            continue

        kelly = _kelly_fraction(best_prob, best_odds)
        stake = min(kelly, max_kelly_fraction)

        rows.append({
            "match_id": mid,
            "side": best_side,
            "model_prob": round(best_prob, 6),
            "bm_implied_prob": round(best_bm_prob, 6),
            "bm_odds": round(best_odds, 4),
            "edge": round(best_edge, 6),
            "kelly_fraction": round(kelly, 6),
            "stake_fraction": round(stake, 6),
        })

    if n_missing_odds:
        logger.debug(
            f"simulation: {n_missing_odds} matches skipped — no bookmaker odds available."
        )
    logger.debug(
        f"simulation: {len(rows)} bets recommended, {n_no_bet} no-bet "
        f"(edge_threshold={edge_threshold})."
    )

    return pd.DataFrame(rows)


def settle_bets(
    bets_df: pd.DataFrame,
    actuals: pd.Series,
    match_id_to_result: dict[int, int | None] | None = None,
) -> pd.DataFrame:
    """
    Attach actual outcomes and profit/loss to a simulated bets DataFrame.

    Args:
        bets_df:             Output of simulate_recommendations().
        actuals:             Series with index=match_id, values=home_win (1/0/None).
                             OR pass match_id_to_result dict instead.
        match_id_to_result:  Alternative to actuals Series. Dict of {match_id: home_win}.

    Returns:
        bets_df with added columns: won (bool|None), profit (float|None).
        Unsettled bets (no result yet) have won=None, profit=None.
    """
    if match_id_to_result is None:
        if not isinstance(actuals, pd.Series):
            raise TypeError("Either actuals (Series) or match_id_to_result (dict) is required.")
        match_id_to_result = actuals.to_dict()

    out = bets_df.copy()

    def _won(row) -> bool | None:
        result = match_id_to_result.get(int(row["match_id"]))
        if result is None:
            return None
        if row["side"] == "home":
            return bool(result == 1)
        return bool(result == 0)

    def _profit(row) -> float | None:
        if row["won"] is None:
            return None
        if row["won"]:
            return row["stake_fraction"] * (row["bm_odds"] - 1.0)
        return -row["stake_fraction"]

    out["won"] = out.apply(_won, axis=1)
    out["profit"] = out.apply(_profit, axis=1)
    return out


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _kelly_fraction(win_prob: float, decimal_odds: float) -> float:
    """
    Full Kelly criterion fraction.

    f = (b * p - q) / b  where b = decimal_odds - 1, q = 1 - p

    Returns 0.0 for negative-edge situations (never bet when Kelly is negative).
    """
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - win_prob
    f = (b * win_prob - q) / b
    return max(0.0, f)
