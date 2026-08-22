# Architecture

**Last verified:** 2026-08-21

---

## 1. System overview

AFL Predict is a batch research pipeline with a thin service layer on top. Data
flows one way — ingest, engineer, model, evaluate, recommend, present. The
database holds all durable records; feature parquet files and model artifacts are
file-based side channels (see §13.1).

Five functional areas:

| Area | Directory | Responsibility |
|---|---|---|
| Ingestion | `collectors/` | Fetch, validate and persist raw external data |
| Feature engineering | `features/` | Turn stored records into one leakage-safe row per match |
| Modelling | `models/` | Fit and serve win probabilities behind one interface |
| Evaluation | `backtesting/`, `evaluation/` | Walk-forward scoring, staking simulation, readiness, CLV |
| Delivery | `orchestration/`, `api/`, `static/` | Schedule the work, expose results, alert |

---

## 2. Architecture diagram

```text
  Squiggle API        The Odds API        Open-Meteo
  (fixtures,          (live H2H odds,     (match-day
   results, odds)      needs a key)        weather)
        |                   |                  |
        +---------+---------+------------------+
                  v
         collectors/   collect -> parse -> validate -> transform -> upsert
                  |    raw payload snapshotted before parsing
                  v
         db/       PostgreSQL (prod) / SQLite (local)
                  |    SQLAlchemy 2.0 + Alembic
                  v
         features/ DatasetBuilder -> one row per match
                  |    parquet + match_features table
                  v
         models/   Elo | Logistic | XGBoost | Poisson | Bookmaker baseline
                  |         |
                  |         +--> calibration (isotonic, out-of-sample)
                  |         +--> ensemble (weights from Settings)
                  |
        +---------+-------------------+
        v                             v
  backtesting/                 orchestration/
  walk-forward folds,          daily_pipeline sequences 13 jobs
  leakage assertion,           edge vs market -> capped Kelly
  Brier/logloss/ECE,           -> paper Recommendation rows
  staking simulation                    |
        |                               |
        v                    +----------+----------+----------+
  result artifacts (JSON)    v          v          v          v
                          FastAPI   static     Discord    evaluation/
                          api/      dashboard  webhook    readiness, CLV
```

---

## 3. Data pipeline

`collectors/`

The primary sources (Squiggle fixtures/results, odds) follow five stages, so a
failure is attributable to one of them rather than to "ingestion". The weather
and FootyWire collectors are simpler and do **not** write raw snapshots:

1. **Collect** — `afl_collector.py`, `odds_api_collector.py`, `weather_collector.py`,
   `player_collector.py`, `footywire_odds_collector.py`, `tab_odds_collector.py`.
   Retries via `tenacity`.
2. **Snapshot** — `snapshot_store.py` writes the raw payload to
   `storage/raw_snapshots/` *before* parsing, so a parser bug is replayable
   without re-hitting the API.
3. **Parse** — `collectors/parsers/` (`squiggle_parser.py`, `odds_parser.py`,
   `timezone_utils.py`).
4. **Validate** — `collectors/validators/` rejects malformed records with a
   reason rather than importing them.
5. **Transform + upsert** — `collectors/transformers/`, keyed on `external_id`.

Cross-cutting: `team_normalizer.py` maps the many spellings of each club to one
canonical team; `venue_rules.py` holds venue/state metadata for travel features.

**Idempotency.** Teams and matches upsert by `external_id`. Scheduling fields are
updated on every run; a match *result* is written once and never overwritten, so
a late upstream correction cannot silently invalidate an already-settled bet.

---

## 4. Feature pipeline

`features/feature_builder.py` — `DatasetBuilder` runs each extractor over the
match table and joins the results into a flat frame, one row per match.
`features/persistence.py` writes it to parquet and upserts `match_features`.

| Extractor | File | Emits |
|---|---|---|
| Elo | `extractors/elo.py` | `home_elo_pre`, `away_elo_pre`, `elo_diff` |
| Form | `extractors/form.py` | Win rates L3/L5/L10, points for/against, momentum |
| Head-to-head | `extractors/h2h.py` | `h2h_home_win_rate_l5`, `h2h_avg_margin_l5`, `h2h_games_played` |
| Venue | `extractors/venue.py`, `venue_performance.py` | Venue win rates, home advantage, `is_neutral_venue` |
| Rest | `extractors/rest.py` | `home_rest_days`, `away_rest_days` |
| Travel | `extractors/travel.py` | Interstate flags, `travel_km`, `travel_km_diff` |
| Bookmaker | `extractors/bookmaker.py` | Odds, implied probabilities, overround |
| Odds movement | `extractors/odds_movement.py` | Opening odds, drift, line move |
| Weather | `extractors/weather.py` | Conditions, `weather_scoring_index` |
| Player availability | `extractors/player_availability.py` | Availability index, key absences — **constant in practice** |

Extractors are independent: adding one cannot change another's output.

**The invariant.** No feature value may depend on information that did not exist
before kickoff. The universal guarantee is the fold-construction assertion
`backtesting/splits.py::_assert_no_leakage`, which raises. Per extractor the
mechanism varies: Elo, form, h2h, venue-performance and rest iterate
chronologically and emit before updating state; bookmaker filters on
`snapshot_time < match_time`; travel and venue are stateless. Extractor-level
leakage tests exist for Elo, form and bookmaker only — see `PROJECT_STATUS.md` §11.

---

## 5. Model layer

`models/base_model.py` defines the contract — `fit`, `predict_proba`, `save`,
`load`, `metadata` — so the trainer, backtester, recommender and demo are all
model-agnostic. `predict_proba` always returns `match_id`, `home_win_prob`,
`away_win_prob`.

| Model | File | Stateful? |
|---|---|---|
| Bookmaker baseline | `bookmaker_baseline.py` | No — market-derived, benchmark only |
| Elo | `elo_baseline.py` | No artifact; ratings carried forward |
| Logistic regression | `logistic_baseline.py` | Fitted sklearn `Pipeline` (median impute → scale → L2 logistic) |
| XGBoost | `xgboost_model.py` | Fitted booster, `random_state=42`, CPU-only as wired |
| Poisson | `poisson_model.py` | Fitted GLM (intercept + `is_final` only) |

---

## 6. Calibration layer

`models/calibrated_model.py` wraps any fitted `BaseModel` with post-hoc isotonic
regression, fitted **out of sample**:

```text
seasons 1 .. N-2   fit the base model
season  N-1        fit the isotonic calibrator on that model's predictions
season  N          evaluate
```

The base model is deliberately **not** refit on 1..N-1 afterwards: an isotonic
calibrator is tied to the output distribution of one specific fitted model, and
refitting the base leaves the calibrator mapping stale probabilities. Applied to
logistic and XGBoost by `orchestration/jobs/train_models.py`.

---

## 7. Evaluation layer

- `backtesting/metrics.py` — Brier, log loss, accuracy, ECE, plus staking metrics.
- `backtesting/calibration.py` — reliability bins and calibration report.
- `backtesting/bootstrap.py` — confidence intervals on ROI, hit rate, Sharpe.
- `evaluation/evaluator.py` — scoring used by the training job.
- `evaluation/live_readiness.py` — gate over sample size, drawdown, ECE, recent job failures. Decision support only; it authorises nothing.
- `evaluation/clv_tracker.py` — closing-line value across settled bets.

---

## 8. Backtesting layer

- `backtesting/splits.py` — expanding and rolling season folds; `_assert_no_leakage` raises `LeakageError` on any violation.
- `backtesting/runner.py` — per fold: fit → predict → simulate → settle → score.
- `backtesting/simulation.py` — edge vs market, capped Kelly staking, settlement.
- `backtesting/artifacts.py` — JSON serialisation (non-finite metrics → `null`, `allow_nan=False`).
- `backtesting/elo_tuner.py`, `xgb_tuner.py` — offline hyperparameter search. **Their output is not used for reported metrics**: they search the same folds that get reported, so `run_backtest --untuned` bypasses them.

Entry point: `orchestration/jobs/run_backtest.py`.

---

## 9. API layer

FastAPI (`api/main.py`), 9 routers:

| Prefix | Module | Purpose |
|---|---|---|
| `/health` | `routes/health.py` | Liveness |
| `/fixtures` | `routes/fixtures.py` | Upcoming and past matches |
| `/predictions` | `routes/predictions.py` | Stored predictions |
| `/recommendations` | `routes/recommendations.py` | Paper recommendations |
| `/dashboard` | `routes/dashboard.py` | Performance, bankroll, freshness, readiness, CLV |
| `/api/dashboard` | `routes/dashboard_ui.py` | Typed surface for the React app |
| `/api/sync` | `routes/data_sync.py` | Cross-machine data sync |
| `/api/tab` | `routes/tab_tracking.py` | Records manually-placed bets for audit |
| `/discord` | `routes/discord_history.py` | Reads back posted alerts |

Read-only with respect to betting. `tab_tracking` records bets a human already
placed elsewhere; it holds no bookmaker credentials and contacts no sportsbook.

**Authentication:** only `/api/sync/*` is protected, by an `X-Sync-Token` header
checked against `api_secret_key` (`_require_sync_token`). The other eight routers
have no auth dependency — see §14.

### Presentation

`static/quant-dashboard/` is the canonical UI: plain JSX transpiled in-browser,
no build step. It boots with a placeholder dataset, then overlays
`predictions.json` and, behind FastAPI, the `/dashboard/*` endpoints. A status
banner reports which source actually applied, including a `SAMPLE DATA` warning
for demo payloads.

`frontend/` is a secondary Vite/React/TypeScript app. `static/dashboard.html` is
a superseded single-file Chart.js dashboard, kept for reference only.

---

## 10. Persistence

SQLAlchemy 2.0 declarative models (`db/models/`) with an Alembic chain from an
empty database (`db/migrations/versions/`, `0000`–`0008`).

| Group | Tables |
|---|---|
| Reference | `teams`, `matches` |
| Raw signals | `odds_snapshots`, `weather_snapshots`, `player_lineups`, `player_stats` |
| Derived | `match_features` |
| Modelling | `model_runs`, `predictions` |
| Decisions | `recommendations`, `bet_outcomes`, `bankroll_logs` |
| Operations | `pipeline_runs`, `daily_pipeline_runs` |

PostgreSQL in the dual-machine deployment, SQLite by default locally.
`alembic upgrade head` is the only supported way to build the schema;
`make db-init` (`create_all`) exists for throwaway inspection and must not be
mixed with Alembic on the same database.

### Model artifact flow

```text
train_models.py
  |- temporal split: seasons 1..N-2 train | N-1 calibrate | N evaluate
  |- fit base model, wrap logistic/XGBoost in isotonic calibration
  |- save -> storage/model_artifacts/run_<id>_<UTC>/<name>_<version>.pkl
  +- insert ModelRun(model_name, brier_score, log_loss, ece, metadata_json)

generate_recommendations.py
  |- for each name in Settings.ensemble_weights:
  |     best ModelRun by Brier whose stored n_features matches the CURRENT schema
  |     (a stale artifact is skipped, not loaded against mismatched columns)
  |- >=2 components -> Ensemble; otherwise the single best model by Brier
  +- predict upcoming -> edge vs market -> capped Kelly -> Recommendation rows
```

Each training run writes to its own immutable directory, so a later run cannot
overwrite the artifact an earlier `ModelRun` row points at.

---

## 11. Automation / scheduling

`orchestration/daily_pipeline.py` runs jobs in dependency order, writes a
`pipeline_runs` row per job and a `daily_pipeline_runs` row per run.

Order (`_ALL_JOBS`, 13 jobs): freshness check → ingest AFL → ingest odds →
build features → generate recommendations → notify → settle results → daily
summary → five role audits (`orchestration/jobs/roles/`).

`fetch_weather` and `fetch_player_stats` are **not** in the daily pipeline; they
are separately scheduled jobs (see `ops/orchestration_24_7.md`).

- Retries apply to network jobs only (`PIPELINE_MAX_RETRIES`); deterministic failures are not retried.
- A hard-dependency failure skips later jobs that are themselves marked `hard_dep=True`. Only the three ingestion/feature jobs carry that flag and none follows `build_features`, so a feature-build failure currently skips nothing — see `PROJECT_STATUS.md` §9.
- Idempotent: safe to re-run the same day. Regenerating recommendations voids stale *pending* rows but preserves any with a `BetOutcome`.

`NODE_ROLE` (`standalone` | `collector` | `predictor`) filters the job list, which
is how the two-machine deployment splits work from one codebase. Wrappers in
`ops/windows_tasks/` and `ops/crontab_server.txt`.

---

## 12. External services

| Service | Used for | Key required | Failure mode |
|---|---|---|---|
| Squiggle API | Fixtures, results, historical consensus odds | No | Ingestion job fails and retries; pipeline gates downstream |
| The Odds API | Live H2H odds | Yes (free tier) | Skipped entirely when `ODDS_API_KEY` is blank |
| Open-Meteo | Match-day weather | No | Weather features null |
| Discord | Webhook alerts + read-back | Yes (optional) | Skipped when `DISCORD_ENABLED=false` |

No sportsbook integration exists.

---

## 13. Key engineering decisions

1. **The database holds the durable records; files are a deliberate side channel.** Model artifacts (`.pkl`) stay local to the machine that produced them, and the feature matrix is written to parquet by `build_features` and read back by `run_backtest` and `train_models`. `api/routes/data_sync.py` can transfer the feature parquet and odds JSON between machines over an authenticated endpoint. `Prediction` and `Recommendation` rows cross via the database. Restoring a predictor means retraining rather than copying model files.
2. **Snapshot before parse.** Raw payloads are stored first, so parser bugs are replayable offline.
3. **One `BaseModel` interface** for `fit` / `predict_proba` / `save` / `load`, so consumers never branch on model type at prediction time. Adding a model still requires registering it where models are enumerated — `train_models.py`, `run_backtest.py` and `generate_recommendations.py` each hold an explicit list.
4. **One source of ensemble weights.** `Settings.ensemble_weights`, keyed by the persisted `ModelRun.model_name`. A previous duplicate table caused the API to report a blend production never ran; the invariant is now asserted by `tests/test_ensemble_config.py`.
5. **Leakage prevention is an assertion, not a convention.** `_assert_no_leakage` raises.
6. **Degrade, don't fail.** A missing or stale model artifact drops that component and the ensemble renormalises; fewer than two components falls back to the single best model.
7. **Reject stale artifacts by schema.** Each candidate `ModelRun`'s stored `n_features` must match the current feature schema.
8. **Results are published untuned.** The tuners search the reported folds, so their output cannot back a publishable metric.
9. **Paper trading is structural, not a flag.** No code path can place a wager.

---

## 14. Known architectural limitations

1. **Eight of nine routers have no authentication.** Only `/api/sync/*` checks a shared-secret header. `/api/tab/*` mutates bankroll records unauthenticated, and `make serve` binds `0.0.0.0`. Safe on a trusted LAN; not safe publicly.
2. **Three UIs** (canonical static dashboard, secondary React app, superseded Chart.js page). Only the first is maintained.
3. **The static dashboard is a design prototype** — panels the data layer does not populate still show placeholder values.
4. **Single points of failure in the dual-machine split**: the collector hosts both the database and the API.
5. **Tuner scripts are structurally contaminated** — they search the folds used for reporting. Making them usable needs a nested walk-forward scheme.
6. **No dependency lockfile**, so evaluation is not bit-reproducible across environments.
7. **`frontend/` is untested and outside CI.**

---

See [`RESULTS.md`](RESULTS.md) for measured evidence, [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
for what currently works, [`methodology.md`](methodology.md) for modelling detail,
and [`operations.md`](operations.md) for running it on a schedule.
