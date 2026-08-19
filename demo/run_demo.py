"""
demo/run_demo.py
-----------------
Credential-free portfolio demo of the AFL Predict modelling pipeline.

What it demonstrates, on the real code path:

    bundled sample pre-match data   (examples/sample_matches.csv)
        -> temporal train/holdout split      (backtesting.splits)
        -> four probabilistic models fitted  (models/*)
        -> settings-weighted ensemble        (models.ensemble)
        -> paper-trade staking decisions     (backtesting.simulation)
        -> dashboard payload                 (static/quant-dashboard/predictions.json)

What it deliberately does NOT do:
  - call any external API (no Squiggle, no Odds API, no weather, no Discord)
  - require an API key, PostgreSQL, or a populated database
  - place, or offer to place, any real-money bet

Everything it prints is derived from the bundled sample file, which holds
completed AFL matches. The most recent round is held out and treated as if it
were upcoming, so the demo can show recommendations *and* score them.

Determinism: the sample data is frozen, models are seeded, and the split is by
calendar round. Two runs on the same checkout produce the same numbers.

Usage:
    make demo
    python -m demo.run_demo
    python -m demo.run_demo --json-only        # skip the console report
    python -m demo.run_demo --write-example    # also refresh the committed example artifact

`make demo` only writes static/quant-dashboard/predictions.json, which is
gitignored, so running the demo never dirties a tracked file. Refreshing the
committed example under examples/ is a deliberate act behind --write-example.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = REPO_ROOT / "examples" / "sample_matches.csv"
PREDICTIONS_JSON = REPO_ROOT / "static" / "quant-dashboard" / "predictions.json"
SUMMARY_JSON = REPO_ROOT / "examples" / "sample_daily_summary.json"
EXAMPLE_PREDICTIONS_JSON = REPO_ROOT / "examples" / "sample_predictions.json"

# Paper-trading parameters. Mirrors config defaults; hard-coded here so the demo
# needs no .env file at all.
EDGE_THRESHOLD = 0.03
MAX_KELLY_FRACTION = 0.05
DEMO_BANKROLL = 1000.0


def _load_sample() -> pd.DataFrame:
    if not SAMPLE_CSV.exists():
        raise SystemExit(
            f"[error] sample data missing: {SAMPLE_CSV}\n"
            "        This file is committed to the repository — re-check out the repo."
        )
    df = pd.read_csv(SAMPLE_CSV, parse_dates=["match_time"])
    df = df.sort_values("match_time").reset_index(drop=True)
    return df


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Hold out the last full home-and-away round of the final season.

    Not the very last round: that is the Grand Final, a single match, which is
    too small to print a meaningful accuracy or Brier score against. The final
    regular round gives a full slate of ~9 matches.

    The split is strictly temporal — every training match kicks off before every
    holdout match. Same leakage rule the real backtester enforces
    (backtesting.splits.check_temporal_order), just with a single fold.
    """
    last_season = int(df["season"].max())
    regular = df[(df["season"] == last_season) & (~df["is_final"].astype(bool))]
    if regular.empty:
        raise SystemExit("[error] sample data has no home-and-away matches in its final season.")
    last_round = int(regular["round_number"].max())

    holdout = regular[regular["round_number"] == last_round]
    train = df[df["match_time"] < holdout["match_time"].min()]

    if holdout.empty or train.empty:
        raise SystemExit("[error] sample data too small to split into train/holdout.")
    assert train["match_time"].max() < holdout["match_time"].min(), "temporal split violated"
    return train.reset_index(drop=True), holdout.reset_index(drop=True)


def _build_models() -> list:
    """
    Instantiate the ensemble components with weights from Settings.

    Weights come from config.settings.Settings.ensemble_weights — the single
    source of truth the production recommendation job reads. A component whose
    optional dependency is unavailable in this environment (XGBoost needs an
    OpenMP runtime) is reported and skipped rather than failing the demo.
    """
    from config.settings import get_settings
    from models.elo_baseline import EloBaseline
    from models.logistic_baseline import LogisticBaseline
    from models.poisson_model import PoissonModel

    factories: dict[str, callable] = {
        "logistic_baseline": LogisticBaseline,
        "poisson": PoissonModel,
        "elo_baseline": EloBaseline,
    }

    try:
        import xgboost  # noqa: F401

        from models.xgboost_model import XGBoostModel

        factories["xgboost"] = XGBoostModel
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[warn] XGBoost unavailable ({type(exc).__name__}) — running without it.")

    components = []
    skipped = []
    for name, weight in get_settings().ensemble_weights.items():
        factory = factories.get(name)
        if factory is None:
            skipped.append(name)
            continue
        components.append((factory(), weight))

    if skipped:
        print(f"[info] not demo components, skipped: {', '.join(skipped)}")
    if len(components) < 2:
        raise SystemExit("[error] fewer than two ensemble components available.")
    return components


def _fit_and_predict(train: pd.DataFrame, holdout: pd.DataFrame):
    """Fit every component plus the ensemble; return per-model probability frames."""
    from models.ensemble import TrainableEnsemble

    components = _build_models()
    y_train = train["home_win"].astype(int)
    X_train = train.drop(columns=["home_win"])
    X_holdout = holdout.drop(columns=["home_win"])

    per_model: dict[str, pd.DataFrame] = {}
    for model, _ in components:
        model.fit(X_train, y_train)
        per_model[model.name] = model.predict_proba(X_holdout)

    # Fresh instances for the ensemble: the components above are already fitted,
    # and TrainableEnsemble.fit would refit them. Sharing them works here but
    # couples two things that should stay independent.
    ensemble = TrainableEnsemble(_build_models())
    ensemble.fit(X_train, y_train)
    per_model["ensemble"] = ensemble.predict_proba(X_holdout)
    return per_model, ensemble.weights


def _recommend(preds: pd.DataFrame, holdout: pd.DataFrame) -> pd.DataFrame:
    """Run the real staking logic over the ensemble's holdout probabilities."""
    from backtesting.simulation import settle_bets, simulate_recommendations

    sim_cols = [
        "match_id",
        "bm_home_implied_prob",
        "bm_away_implied_prob",
        "bm_home_odds",
        "bm_away_odds",
        "match_time",
    ]
    bets = simulate_recommendations(
        preds,
        holdout[sim_cols],
        edge_threshold=EDGE_THRESHOLD,
        max_kelly_fraction=MAX_KELLY_FRACTION,
    )
    if bets.empty:
        return bets

    actuals = holdout.set_index("match_id")["home_win"].reindex(preds["match_id"])
    result_map = {
        int(mid): int(hw) for mid, hw in zip(holdout["match_id"], holdout["home_win"])
    }
    return settle_bets(bets, actuals, match_id_to_result=result_map)


def _metrics(preds: pd.DataFrame, holdout: pd.DataFrame) -> dict:
    from backtesting.metrics import compute_metrics

    actuals = holdout.set_index("match_id")["home_win"].reindex(preds["match_id"])
    wm = compute_metrics(
        model_name="demo",
        fold_label="holdout",
        predictions_df=preds,
        actuals=actuals,
        simulated_bets=None,
    )
    return wm.to_dict()


def _confidence(prob: float) -> str:
    edge = abs(prob - 0.5) + 0.5
    if edge >= 0.65:
        return "HIGH"
    if edge >= 0.55:
        return "MED"
    return "LOW"


def _build_payload(
    holdout: pd.DataFrame,
    per_model: dict[str, pd.DataFrame],
    bets: pd.DataFrame,
    weights: dict[str, float],
) -> dict:
    """Assemble the predictions.json contract the static dashboard fetches."""
    ens = per_model["ensemble"].set_index("match_id")
    by_model = {
        key: per_model[name].set_index("match_id")["home_win_prob"]
        for key, name in (
            ("xgboost_prob", "xgboost"),
            ("poisson_prob", "poisson"),
            ("elo_prob", "elo_baseline"),
            ("logistic_prob", "logistic_baseline"),
        )
        if name in per_model
    }

    stake_by_match: dict[int, dict] = {}
    if not bets.empty:
        for _, b in bets.iterrows():
            stake_by_match[int(b["match_id"])] = {
                "side": b["side"],
                "stake": round(float(b["stake_fraction"]) * DEMO_BANKROLL, 2),
                "edge": round(float(b["edge"]), 4),
                "odds": round(float(b["bm_odds"]), 3),
            }

    games = []
    for _, row in holdout.iterrows():
        mid = int(row["match_id"])
        if mid not in ens.index:
            continue
        prob = float(ens.loc[mid, "home_win_prob"])
        bet = stake_by_match.get(mid)
        games.append(
            {
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "game_date": pd.Timestamp(row["match_time"]).date().isoformat(),
                "venue": row["venue"],
                "model_prediction": row["home_team"] if prob >= 0.5 else row["away_team"],
                "home_win_prob": round(prob, 4),
                "confidence": _confidence(prob),
                "bet_recommended": bet is not None,
                "bet_amount": bet["stake"] if bet else 0.0,
                "bet_side": bet["side"] if bet else None,
                "edge": bet["edge"] if bet else None,
                "tab_odds": round(float(row["bm_home_odds"]), 3),
                **{
                    k: (round(float(s.loc[mid]), 4) if mid in s.index else None)
                    for k, s in by_model.items()
                },
                # Sample data is historical, so the true result is known. Kept
                # separate from the prediction fields so nothing downstream can
                # mistake it for a pre-match input.
                "actual_home_win": int(row["home_win"]),
            }
        )

    # settle_bets adds `won` (bool|None) and `profit` (stake-fraction units).
    if bets.empty:
        settled = bets
        n_won, pnl = 0, 0.0
    else:
        settled = bets[bets["won"].notna()]
        n_won = int(settled["won"].astype(bool).sum())
        pnl = round(float(settled["profit"].sum()) * DEMO_BANKROLL, 2)

    ens_metrics = _metrics(per_model["ensemble"], holdout)
    correct = sum(
        1
        for g in games
        if (g["home_win_prob"] >= 0.5) == bool(g["actual_home_win"])
    )

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "season": int(holdout["season"].iloc[0]),
        "round": int(holdout["round_number"].iloc[0]),
        "demo": True,
        "demo_notice": (
            "SAMPLE DATA — generated by `make demo` from examples/sample_matches.csv. "
            "Historical completed matches replayed as if upcoming. Not a live forecast. "
            "Paper trading only: no real-money bet is placed anywhere in this repository."
        ),
        "games": games,
        "summary": {
            "total_bets_today": len(stake_by_match),
            "total_amount": round(sum(b["stake"] for b in stake_by_match.values()), 2),
            "paper_trade": True,
        },
        "performance": {
            "total_predictions": len(games),
            "correct": correct,
            "accuracy": round(correct / len(games), 4) if games else 0.0,
            "total_pnl": pnl,
            "current_streak": 0,
            "brier_score": ens_metrics.get("brier_score"),
            "log_loss": ens_metrics.get("log_loss"),
            "bets_won": n_won,
            "bets_settled": int(len(settled)) if not settled.empty else 0,
        },
        "ensemble_weights": {k: round(v, 4) for k, v in weights.items()},
    }


def _report(payload: dict, train_rows: int, wrote_example: bool = False) -> None:
    p = payload
    line = "-" * 74
    print(f"\n{line}")
    print("  AFL PREDICT — PORTFOLIO DEMO   (sample data · paper trading only)")
    print(line)
    print("  Sample file      examples/sample_matches.csv")
    print(f"  Trained on       {train_rows} completed matches (strictly earlier kickoffs)")
    print(f"  Holdout slate    {p['season']} round {p['round']} — {len(p['games'])} matches")
    print(f"  Ensemble weights {p['ensemble_weights']}")
    print(line)
    print(f"  {'MATCH':<38}{'P(home)':>8}  {'CONF':<5}{'PAPER BET':<22}")
    print(line)
    for g in p["games"]:
        match = f"{g['home_team']} v {g['away_team']}"
        bet = (
            f"${g['bet_amount']:.2f} on {g['bet_side']} @ {g['tab_odds']}"
            if g["bet_recommended"]
            else "no bet (edge below threshold)"
        )
        print(
            f"  {match[:37]:<38}{g['home_win_prob']:>8.3f}  "
            f"{g['confidence']:<5}{bet:<22}"
        )
    print(line)
    perf = p["performance"]

    def _fmt(value: float | None) -> str:
        # compute_metrics returns None below its minimum sample size rather than
        # a misleadingly precise number off two matches.
        return f"{value:.4f}" if value is not None else "n/a (sample too small)"

    print(
        f"  Ensemble on holdout: accuracy {perf['accuracy']:.1%} "
        f"({perf['correct']}/{perf['total_predictions']})  "
        f"Brier {_fmt(perf['brier_score'])}  log loss {_fmt(perf['log_loss'])}"
    )
    print(
        f"  Paper staking: {p['summary']['total_bets_today']} bet(s), "
        f"${p['summary']['total_amount']:.2f} of a ${DEMO_BANKROLL:.0f} notional bankroll, "
        f"{perf['bets_won']}/{perf['bets_settled']} won, P&L ${perf['total_pnl']:+.2f}"
    )
    print(line)
    print("  Read those two lines together — they are the point of the project.")
    print("  The forecasts are sharp, and the staking rule still loses money: the")
    print("  models regress strong favourites toward the mean, so most of the 'edge'")
    print("  they find sits on longshots where they are simply less confident than")
    print("  the market. One round of 10 matches proves nothing either way; the")
    print("  full walk-forward evaluation across seasons is in docs/results.md.")
    print(line)
    print("\n  Wrote:")
    print("    static/quant-dashboard/predictions.json   (dashboard payload)")
    if wrote_example:
        print("    examples/sample_daily_summary.json        (committed example artifact)")
        print("    examples/sample_predictions.json          (committed example artifact)")
    print("\n  View the dashboard:")
    print("    python serve.py     ->  http://localhost:8080")
    print("\n  Or serve it behind the API (needs `python -m alembic upgrade head` first):")
    print("    make serve          ->  http://localhost:8000/static/quant-dashboard/index.html")
    print()


def _write_summary_artifact(payload: dict) -> None:
    """Write the committed example artifacts under examples/.

    Two files, both derived from this run:
      - sample_daily_summary.json  — the shape orchestration writes daily
      - sample_predictions.json    — the shape the static dashboard fetches

    Both are safe to publish: the sample data behind them is public AFL results
    and public market-consensus probabilities. No credentials, account
    identifiers, or personal data pass through this path.
    """
    artifact = {
        "date": payload["generated_at"][:10],
        "generated_at": payload["generated_at"],
        "demo": True,
        "demo_notice": payload["demo_notice"],
        "pipeline": {
            "status": "success",
            "triggered_by": "make demo",
            "jobs": [
                {"name": "load_sample_data", "status": "success"},
                {"name": "train_models", "status": "success"},
                {"name": "generate_recommendations", "status": "success"},
            ],
        },
        "recommendations": {
            "n_recommended": payload["summary"]["total_bets_today"],
            "total_staked": payload["summary"]["total_amount"],
            "paper_trade": True,
        },
        "model": {
            "ensemble_weights": payload["ensemble_weights"],
            "holdout_season": payload["season"],
            "holdout_round": payload["round"],
            "brier_score": payload["performance"]["brier_score"],
            "log_loss": payload["performance"]["log_loss"],
            "accuracy": payload["performance"]["accuracy"],
        },
    }
    SUMMARY_JSON.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    EXAMPLE_PREDICTIONS_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the credential-free portfolio demo.")
    parser.add_argument(
        "--json-only", action="store_true", help="Write artifacts without the console report."
    )
    parser.add_argument(
        "--write-example",
        action="store_true",
        help=(
            "Also rewrite examples/sample_daily_summary.json, the committed example "
            "artifact. Left off by default so a demo run never dirties a tracked file."
        ),
    )
    args = parser.parse_args(argv)

    # Keep loguru's per-model INFO chatter out of the demo report.
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    df = _load_sample()
    train, holdout = _split(df)
    per_model, weights = _fit_and_predict(train, holdout)
    bets = _recommend(per_model["ensemble"], holdout)
    payload = _build_payload(holdout, per_model, bets, weights)

    PREDICTIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    PREDICTIONS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.write_example:
        _write_summary_artifact(payload)

    if not args.json_only:
        _report(payload, train_rows=len(train), wrote_example=args.write_example)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
