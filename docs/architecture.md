# Architecture

## System shape

```text
                       ┌──────────────────────────────────────┐
 EXTERNAL SOURCES      │ Squiggle API   fixtures, results     │
                       │ The Odds API   live H2H prices       │
                       │ Open-Meteo     match-day weather     │
                       └──────────────────┬───────────────────┘
                                          │
 ┌────────────────────────────────────────▼───────────────────────────────────┐
 │ collectors/                                                                │
 │   collect → parse → validate → transform → upsert                          │
 │   Every source follows those five stages. Raw responses are snapshotted to  │
 │   storage/raw_snapshots/ before parsing, so a parser bug is replayable.     │
 └────────────────────────────────────────┬───────────────────────────────────┘
                                          │
 ┌────────────────────────────────────────▼───────────────────────────────────┐
 │ db/  (PostgreSQL in production, SQLite locally)                            │
 │   teams · matches · odds_snapshots · weather_snapshots · player_lineups     │
 │   match_features · model_runs · predictions · recommendations               │
 │   bet_outcomes · bankroll_logs · pipeline_runs · daily_pipeline_runs        │
 └────────────────────────────────────────┬───────────────────────────────────┘
                                          │
 ┌────────────────────────────────────────▼───────────────────────────────────┐
 │ features/                                                                  │
 │   DatasetBuilder runs each extractor over the match table and emits one     │
 │   row per match. Every extractor reads only data timestamped before that    │
 │   match's kickoff. Output → parquet + the match_features table.             │
 └────────────────────────────────────────┬───────────────────────────────────┘
                                          │
              ┌───────────────────────────┴───────────────────────────┐
              │                                                       │
 ┌────────────▼──────────────┐                        ┌───────────────▼──────────────┐
 │ models/  (training)       │                        │ backtesting/  (evaluation)   │
 │   Elo · Logistic ·        │                        │   Expanding/rolling splits,  │
 │   XGBoost · Poisson ·     │                        │   leakage assertions, Brier/ │
 │   Bookmaker baseline      │                        │   log loss/ECE, staking sim, │
 │   + isotonic calibration  │                        │   bootstrap CIs              │
 │   + weighted ensemble     │                        └──────────────────────────────┘
 └────────────┬──────────────┘
              │  artifacts (.pkl) + ModelRun rows with metrics
 ┌────────────▼───────────────────────────────────────────────────────────────┐
 │ orchestration/jobs/generate_recommendations.py                             │
 │   Loads the best run of each ensemble component, blends with               │
 │   Settings.ensemble_weights, computes edge vs. market, sizes with capped    │
 │   Kelly, writes Prediction + Recommendation rows.  paper_trade = True.      │
 └────────────┬───────────────────────────────────────────────────────────────┘
              │
       ┌──────┴───────┬──────────────────┬─────────────────────┐
       ▼              ▼                  ▼                     ▼
 ┌───────────┐ ┌────────────┐ ┌────────────────────┐ ┌──────────────────┐
 │ FastAPI   │ │ Static     │ │ Discord webhook    │ │ evaluation/      │
 │ api/      │ │ dashboard  │ │ (alerts only)      │ │ readiness · CLV  │
 └───────────┘ └────────────┘ └────────────────────┘ └──────────────────┘
```

## Components

### `collectors/` — ingestion

| Collector | Source | Notes |
|---|---|---|
| `afl_collector` / `squiggle_collector` | Squiggle API | Fixtures, results, teams. Free, public, no key. |
| `odds_api_collector` / `tab_odds_collector` | The Odds API | Live AU H2H prices. Needs a key; skipped when blank. |
| `footywire_odds_collector` | FootyWire | Historical odds scrape (secondary). |
| `weather_collector` | Open-Meteo | Match-day conditions by venue. |
| `player_collector` | Squiggle / AFL Tables | Lineups and participation. |
| `discord_reader` | Discord bot | Reads back posted alerts for the dashboard history view. |

Shared support: `team_normalizer.py` maps the many spellings of each club to one
canonical team; `snapshot_store.py` writes the raw payload before parsing;
`validators/` rejects malformed records with a reason rather than importing them.

Ingestion is **idempotent**. Teams and matches upsert by `external_id`.
A match result is written once and never overwritten, so a late correction
upstream cannot silently invalidate a settled bet.

### `db/` — persistence

SQLAlchemy 2.0 declarative models with an Alembic migration chain from an empty
database (`0000_initial_schema` onward). PostgreSQL in the dual-machine
deployment, SQLite by default for local work.

`alembic upgrade head` is the only supported way to build the schema.
`make db-init` (`Base.metadata.create_all`) exists for throwaway inspection and
must not be mixed with Alembic on the same database — the two produce
overlapping DDL and will collide.

### `features/` — feature engineering

`FeatureBuilder` composes independent extractors under `features/extractors/`:
Elo, form, rest, venue, head-to-head, travel, weather, bookmaker, availability.
Each returns per-match columns; the builder joins them into a flat frame,
persists it to parquet and to `match_features`.

The single invariant every extractor upholds: **no value may depend on
information that did not exist before kickoff.** See
[`methodology.md`](methodology.md).

### `models/` — forecasting

All models implement `BaseModel` (`fit`, `predict_proba`, `save`, `load`,
`metadata`), so the trainer, backtester and recommendation job are all
model-agnostic. `predict_proba` always returns `match_id`, `home_win_prob`,
`away_win_prob`.

`CalibratedModel` wraps a base model with isotonic or Platt calibration.
`Ensemble` takes `(model, weight)` pairs, normalises the weights, and
renormalises at predict time over whichever components responded — a component
that fails degrades the blend instead of the request.

### `backtesting/` — evaluation

`splits.py` builds expanding or rolling season folds and asserts temporal order.
`runner.py` drives fit → predict → simulate → settle → score per fold.
`metrics.py` computes Brier, log loss, accuracy, ECE plus staking metrics;
`bootstrap.py` adds confidence intervals; `artifacts.py` serialises the result.
`elo_tuner.py` / `xgb_tuner.py` are offline hyperparameter searches whose output
lands in `storage/model_artifacts/*_best_params.json`.

### `orchestration/` — scheduling

`daily_pipeline.py` runs jobs in dependency order, records each in
`pipeline_runs`, retries network jobs, and marks hard-dependency failures so
downstream jobs are skipped rather than run on stale inputs. It filters its job
list by `NODE_ROLE`, which is how the two-machine deployment splits work. Jobs
under `orchestration/jobs/roles/` are per-role daily audits (data, features,
models, risk, review).

### `api/` — service layer

FastAPI. `/health`, `/dashboard/*` (performance, bankroll, recommendations,
freshness, readiness, CLV), `/api/dashboard/*` (the richer typed surface the
React app consumes), plus fixtures, predictions, recommendations, Discord
history and manual bet tracking.

Read-only with respect to betting. `tab_tracking.py` records bets a human
already placed elsewhere, for audit; it holds no bookmaker credentials and
contacts no sportsbook.

### Presentation

`static/quant-dashboard/` is the canonical UI: plain JSX transpiled in-browser,
no build step. It boots with a placeholder dataset, then overlays
`predictions.json` and, when served behind FastAPI, the `/dashboard/*`
endpoints. The status banner states which source actually applied — including a
`SAMPLE DATA` warning when the payload came from `make demo`.

`frontend/` is a Vite/React/TypeScript app covering the same endpoints. It is a
secondary interface and is not the one to look at first.

`static/dashboard.html` is an earlier single-file Chart.js dashboard, superseded
by the quant dashboard and kept for reference only. Nothing routes to it by
default.

## Model artifact flow

```text
train_models.py
  ├─ temporal split: seasons 1..N-2 train · N-1 calibrate · N evaluate
  ├─ fit base model, wrap in isotonic calibration (logistic, XGBoost)
  ├─ save → storage/model_artifacts/run_<id>_<UTC>/<name>_<version>.pkl
  └─ insert ModelRun(model_name, brier_score, log_loss, ece, metadata_json)

generate_recommendations.py
  ├─ for each name in Settings.ensemble_weights:
  │     best ModelRun by Brier whose metadata n_features matches the CURRENT
  │     feature schema  (a stale artifact is skipped, not loaded)
  ├─ ≥2 components → Ensemble; otherwise single best model
  └─ predict upcoming → edge vs market → capped Kelly → Recommendation rows
```

Each training run writes to its own immutable directory, so a later run cannot
overwrite the artifact an earlier `ModelRun` row points at.

## Related documents

- [`methodology.md`](methodology.md) — features, leakage, calibration, validation
- [`results.md`](results.md) — verified evaluation results
- [`operations.md`](operations.md) — running it on a schedule
- [`ingestion.md`](ingestion.md), [`features.md`](features.md), [`backtesting.md`](backtesting.md) — subsystem deep dives
