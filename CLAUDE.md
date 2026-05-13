# CLAUDE.md — AFL_predict project guide

Paper-trading AFL betting research system. **Analytics and alerts only — no
automatic bet placement.** The dashboard surfaces model performance,
recommendations and bankroll state; it never executes wagers.

## Layout (top level)

```text
api/                 FastAPI service: /dashboard/*, /api/dashboard/*, /discord/*
collectors/          raw data ingestion (AFL fixtures, TAB odds, weather, Discord)
config/              environment-driven settings (.env)
db/                  SQLAlchemy models + Alembic migrations
features/            feature engineering (ELO, form, rest, venue, H2H, travel, weather)
models/              prediction + calibration models (logistic, XGBoost, Poisson, Elo)
evaluation/          metrics, live-readiness gate, CLV tracker
orchestration/       daily pipeline jobs (ingest → features → train → recommend → settle → notify)
backtesting/         walk-forward backtests, tuner scripts
static/dashboard.html        legacy Chart.js dashboard (live)
static/quant-dashboard/      Quant dashboard from the Claude Design handoff
frontend/            Vite/React/TS scaffold (Phase B placeholder, separate from quant-dashboard)
tests/               pytest suite
generate_predictions_json.py CSV → predictions.json converter (this file)
serve.py             stdlib HTTP server for standalone dashboard preview
```

## Data flow: pipeline → predictions.json → dashboard

```
┌─────────────────────────────────────────────────────────────────────────┐
│ collectors/  raw fixtures, odds, weather, player availability           │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ features/feature_builder.py                                             │
│   DatasetBuilder runs each extractor, produces a flat feature DataFrame │
│   (one row per match) and persists it to parquet + the                  │
│   match_features DB table.                                              │
└──────────┬──────────────────────────────────────────────────────────────┘
           │                                            (optional CSV export)
           │  data/processed/features_latest_2026.csv  ←────────────────┐
           ▼                                                            │
┌─────────────────────────────────────────────────────────────────────────┐
│ models/                                                                  │
│   logistic_baseline, xgboost_model, poisson_model, elo_baseline,         │
│   bookmaker_baseline, calibrated_model (Isotonic / Platt).               │
│   Ensembled by config.settings.ensemble_weight_* in                       │
│   orchestration/jobs/generate_recommendations.py.                         │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ orchestration/jobs/generate_recommendations.py                          │
│   Writes Prediction + Recommendation rows to the DB and emits the daily │
│   storage/daily_summaries/YYYY-MM-DD.json artifact.                     │
│   (Discord notification: orchestration/jobs/notify_bets.py)             │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ python generate_predictions_json.py                                     │
│   Reads the feature CSV and emits static/quant-dashboard/predictions.json│
│   in the shape the dashboard expects:                                   │
│   { generated_at, season, round, games[], summary, performance }.       │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ static/quant-dashboard/                                                  │
│   index.html boots, data.jsx ships dummy data immediately, then fetches  │
│   ./predictions.json and overlays game cards + KPI numbers when present. │
│   If the file is missing it logs and stays on the bundled dummy dataset. │
│   When served behind FastAPI, live-data.jsx ALSO overlays from           │
│   /dashboard/* endpoints (whichever resolves later wins for re-render).  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Two ways to run the dashboard

### A — full stack (FastAPI + DB; preferred when developing the system)

```bash
make serve   # uvicorn api.main:app --reload --port 8000
# open http://localhost:8000/static/quant-dashboard/index.html
```

`live-data.jsx` queries `/dashboard/performance`, `/dashboard/bankroll`,
`/dashboard/recommendations`, `/dashboard/freshness`, `/dashboard/readiness`,
`/dashboard/clv`, and `/discord/status`. The status banner under the topbar
reports what was overlaid.

### B — standalone preview (no FastAPI, just a JSON file)

```bash
python generate_predictions_json.py            # writes static/quant-dashboard/predictions.json
python serve.py                                 # serves on http://localhost:8080
# open http://localhost:8080/
```

`data.jsx` fetches `./predictions.json`. Missing file → dummy fallback.
This is the mode the design handoff was wired for; it gives an offline
preview of the latest model output without standing up the backend.

## predictions.json schema (contract between Python and the dashboard)

```jsonc
{
  "generated_at": "2026-05-11T08:00:00",
  "season": 2026,
  "round": 12,
  "games": [
    {
      "home_team": "Collingwood",
      "away_team": "Carlton",
      "game_date": "2026-05-11",
      "venue": "MCG",
      "model_prediction": "Collingwood",
      "home_win_prob": 0.67,
      "confidence": "HIGH",           // LOW | MED | HIGH (banded from prob)
      "bet_recommended": true,
      "bet_amount": 4.50,             // AUD, paper
      "tab_odds": 1.85,
      "xgboost_prob": 0.65,
      "poisson_prob": 0.70,
      "elo_prob": 0.66
    }
  ],
  "summary": {
    "total_bets_today": 2,
    "total_amount": 9.00,
    "paper_trade": true
  },
  "performance": {
    "total_predictions": 45,
    "correct": 26,
    "accuracy": 0.578,
    "total_pnl": -3.50,
    "current_streak": 3
  }
}
```

The Python generator is tolerant to missing CSV columns — fields it cannot
resolve are emitted as `null` or zero so the dashboard still renders.

## Operational notes

- **Paper trading only.** `notify_bets.py` posts Discord messages, never
  places wagers. `tab_tracking.py` records manually-placed bets for audit;
  it does not interact with any sportsbook account.
- **Live readiness** lives in `evaluation/live_readiness.py`. Even when the
  report returns `ready`, transition to live is a manual operator decision.
- **Secrets** (Discord, odds API) stay in `.env`. Never commit credentials.
- **Daily pipeline:** `make pipeline` or `python -m orchestration.daily_pipeline`.

## Useful Make targets

| Target | Purpose |
|---|---|
| `make serve` | Start FastAPI on :8000 |
| `make pipeline` | Run the full daily pipeline manually |
| `make daily-summary` | Write today's `storage/daily_summaries/{date}.json` |
| `make readiness` | Evaluate the live-readiness gate |
| `make clv` | Print CLV summary across settled bets |
| `make notify` | Send today's value picks to the Discord webhook |
| `make test` | Run pytest |
| `make lint` | `ruff check .` |
