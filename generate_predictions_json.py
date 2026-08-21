"""
generate_predictions_json.py
-----------------------------
Generate the `predictions.json` artifact that the static Quant Dashboard
fetches at boot. Reads a pre-match feature CSV produced by the feature
pipeline and emits the dashboard's expected JSON shape.

Usage:
    python generate_predictions_json.py
    python generate_predictions_json.py --input data/processed/features_latest_2026.csv \\
                                        --output static/quant-dashboard/predictions.json
    python generate_predictions_json.py --season 2026 --round 12

Expected (or close-variant) columns in the input CSV:
    home_team, away_team, game_date / match_date / kickoff,
    venue, home_win_prob (model ensemble),
    xgboost_prob, poisson_prob, elo_prob,
    tab_odds / home_odds / bm_home_odds, away_odds / bm_away_odds,
    bet_recommended, bet_amount,
    season, round / round_number.

The script is tolerant to missing columns — fields are emitted as null or
sensible defaults so the dashboard still renders. Pure analytics: no bet
placement, no real-money execution.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = REPO_ROOT / "data" / "processed" / "features_latest_2026.csv"
DEFAULT_OUTPUT = REPO_ROOT / "static" / "quant-dashboard" / "predictions.json"

CONFIDENCE_HIGH = 0.65
CONFIDENCE_MED = 0.55


def _first_present(row: dict, *keys: str, default: Any = None) -> Any:
    """Return the first non-null value across candidate column names."""
    for k in keys:
        if k in row and row[k] is not None and not _is_nan(row[k]):
            return row[k]
    return default


def _is_nan(value: Any) -> bool:
    try:
        return isinstance(value, float) and math.isnan(value)
    except Exception:
        return False


def _to_float(value: Any) -> float | None:
    if value is None or _is_nan(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or _is_nan(value):
        return False
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "y", "t")


def _confidence_label(prob: float | None) -> str:
    if prob is None:
        return "LOW"
    p = abs(prob - 0.5) + 0.5  # distance from coin-flip
    if p >= CONFIDENCE_HIGH:
        return "HIGH"
    if p >= CONFIDENCE_MED:
        return "MED"
    return "LOW"


def _row_to_game(row: dict) -> dict[str, Any]:
    home = _first_present(row, "home_team", "home_team_name", "home", default="Home")
    away = _first_present(row, "away_team", "away_team_name", "away", default="Away")
    venue = _first_present(row, "venue", "venue_name", "stadium", default="")
    game_date = _first_present(
        row, "game_date", "match_date", "kickoff", "match_time", default=""
    )
    if hasattr(game_date, "isoformat"):
        game_date = game_date.isoformat()
    else:
        game_date = str(game_date) if game_date else ""

    home_win_prob = _to_float(
        _first_present(row, "home_win_prob", "ensemble_home_prob", "prob_home_win")
    )
    xgb = _to_float(_first_present(row, "xgboost_prob", "xgb_home_prob"))
    poi = _to_float(_first_present(row, "poisson_prob", "poisson_home_prob"))
    elo = _to_float(_first_present(row, "elo_prob", "elo_home_prob"))

    # If ensemble missing, average the per-model probs that are present.
    if home_win_prob is None:
        parts = [v for v in (xgb, poi, elo) if v is not None]
        home_win_prob = sum(parts) / len(parts) if parts else None

    # Emit BOTH sides. The dashboard pairs each probability with its own side's
    # price; if only the home price is present it shows the away row's odds and
    # edge as unavailable rather than borrowing the home number.
    home_odds = _to_float(
        _first_present(row, "tab_odds", "home_odds", "bm_home_odds", "best_home_odds")
    )
    away_odds = _to_float(_first_present(row, "away_odds", "bm_away_odds", "best_away_odds"))
    tab_odds = home_odds  # `tab_odds` is the HOME price by definition.
    bet_recommended = _to_bool(_first_present(row, "bet_recommended", default=False))
    bet_amount = _to_float(_first_present(row, "bet_amount", "stake_dollars", default=0)) or 0.0

    if home_win_prob is None:
        model_prediction = ""
    else:
        model_prediction = home if home_win_prob >= 0.5 else away

    return {
        "home_team": str(home),
        "away_team": str(away),
        "game_date": game_date,
        "venue": str(venue),
        "model_prediction": str(model_prediction),
        "home_win_prob": round(home_win_prob, 4) if home_win_prob is not None else None,
        "confidence": _confidence_label(home_win_prob),
        "bet_recommended": bool(bet_recommended),
        "bet_amount": round(float(bet_amount), 2),
        "home_odds": round(home_odds, 3) if home_odds is not None else None,
        "away_odds": round(away_odds, 3) if away_odds is not None else None,
        # Retained for the existing predictions.json contract; equals home_odds.
        "tab_odds": round(tab_odds, 3) if tab_odds is not None else None,
        "xgboost_prob": round(xgb, 4) if xgb is not None else None,
        "poisson_prob": round(poi, 4) if poi is not None else None,
        "elo_prob": round(elo, 4) if elo is not None else None,
    }


def _load_rows(input_path: Path) -> list[dict]:
    """Read CSV via pandas if available, falling back to stdlib csv."""
    if not input_path.exists():
        return []
    try:
        import pandas as pd  # type: ignore[import-not-found]

        df = pd.read_csv(input_path)
        return df.to_dict(orient="records")
    except ImportError:
        import csv

        with open(input_path, encoding="utf-8") as f:
            return list(csv.DictReader(f))


def _performance_block(rows: list[dict]) -> dict[str, Any]:
    """Aggregate season-to-date performance fields from settled rows.

    Settled rows are recognised by the presence of a `result` / `won`
    / `actual_winner` column. Missing inputs produce zeros so the dashboard
    still has shape-correct data.
    """
    total = 0
    correct = 0
    pnl = 0.0
    last_results: list[bool] = []
    for row in rows:
        settled = _first_present(row, "settled", default=None)
        if settled is not None and not _to_bool(settled):
            continue
        actual = _first_present(row, "actual_winner", "result", "won", default=None)
        if actual is None or _is_nan(actual):
            continue
        total += 1
        prediction = _first_present(row, "model_prediction", default=None)
        was_correct: bool | None = None
        if isinstance(actual, str) and prediction:
            was_correct = str(actual).strip().lower() == str(prediction).strip().lower()
        else:
            was_correct = _to_bool(actual)
        if was_correct:
            correct += 1
        last_results.append(bool(was_correct))
        pl = _to_float(_first_present(row, "pl", "profit_loss", "pnl"))
        if pl is not None:
            pnl += pl

    accuracy = round(correct / total, 4) if total > 0 else 0.0

    streak = 0
    for hit in reversed(last_results):
        if hit:
            streak += 1
        else:
            break

    return {
        "total_predictions": total,
        "correct": correct,
        "accuracy": accuracy,
        "total_pnl": round(pnl, 2),
        "current_streak": streak,
    }


def _summary_block(games: list[dict]) -> dict[str, Any]:
    bets = [g for g in games if g.get("bet_recommended")]
    total_amount = round(sum(_to_float(g.get("bet_amount")) or 0.0 for g in bets), 2)
    return {
        "total_bets_today": len(bets),
        "total_amount": total_amount,
        "paper_trade": True,
    }


def generate(
    input_path: Path,
    output_path: Path,
    season: int | None = None,
    round_number: int | None = None,
) -> dict[str, Any]:
    rows = _load_rows(input_path)
    games = [_row_to_game(r) for r in rows] if rows else []

    # Infer season / round from the first row if not provided on the CLI.
    season_resolved = season
    round_resolved = round_number
    if rows and (season_resolved is None or round_resolved is None):
        first = rows[0]
        if season_resolved is None:
            season_resolved = _to_int(_first_present(first, "season"))
        if round_resolved is None:
            round_resolved = _to_int(
                _first_present(first, "round", "round_number", "round_num")
            )

    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "season": season_resolved if season_resolved is not None else 0,
        "round": round_resolved if round_resolved is not None else 0,
        "games": games,
        "summary": _summary_block(games),
        "performance": _performance_block(rows),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                   help=f"Input feature CSV (default: {DEFAULT_INPUT.relative_to(REPO_ROOT)})")
    p.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                   help=f"Output JSON file (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})")
    p.add_argument("--season", type=int, default=None, help="Override season in the output.")
    p.add_argument("--round", dest="round_number", type=int, default=None,
                   help="Override round number in the output.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.input.exists():
        print(
            f"[warn] input CSV not found: {args.input}. "
            "Writing an empty predictions.json so the dashboard still loads.",
            file=sys.stderr,
        )

    payload = generate(args.input, args.output, args.season, args.round_number)
    print(
        f"[ok] wrote {args.output}: "
        f"{len(payload['games'])} games, "
        f"{payload['summary']['total_bets_today']} bets today, "
        f"acc={payload['performance']['accuracy']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
