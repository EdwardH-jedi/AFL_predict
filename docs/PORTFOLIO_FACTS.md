# AFL Predict — Portfolio Facts

**One line:** A paper-trading-first AFL match-prediction research system that
tests whether calibrated model ensembles can find value against bookmaker
prices — with a leakage-controlled walk-forward backtest and no live-money
automation.

**Purpose.** Research and engineering exercise: build the full pipeline a
quantitative sports-betting shop would need (ingestion → features → models →
staking → evaluation → ops), then evaluate honestly whether the models add
value. It is explicitly *not* a betting product.

**Stack.** Python 3.11, FastAPI + uvicorn, SQLAlchemy 2 + Alembic
(SQLite/PostgreSQL), pydantic-settings, scikit-learn, XGBoost (CUDA-aware),
statsmodels, pandas/pyarrow, pytest + ruff, React/TypeScript (Vite) dashboard,
Discord webhooks for alerts.

**Architecture.** Modular daily pipeline (`orchestration/`) with a state
machine and per-job retries: collectors (Squiggle fixtures, The Odds API odds,
Open-Meteo weather, AFL Tables player stats) → 11 feature extractors with an
enforced pre-match leakage policy → five models (bookmaker baseline, Elo,
logistic, XGBoost, Poisson) with isotonic calibration and a weighted ensemble
→ Kelly-capped paper staking with abstention rules → evaluation (Brier, log
loss, ECE, CLV) and a 7-check live-readiness gate → FastAPI dashboard +
Discord notifications. Supports a two-machine split (collector node /
GPU predictor node) via a `NODE_ROLE` setting.

**What is implemented.** End-to-end ingestion, feature building, training
with temporal splits, expanding/rolling-window walk-forward backtesting,
grid-search hyperparameter tuning (XGBoost, Elo), calibration with ECE
tracking, CLV tracking, recommendation generation with Kelly-capped stakes,
daily-summary artifacts, role-based audit jobs, Alembic migration chain
(0000–0008), and two dashboards.

**Evaluation method.** Walk-forward (expanding-window) backtests split by
season; leakage prevented at extractor level (`snapshot_time < match_time`)
and asserted at split level (`LeakageError` on temporal overlap). The
backtest runner evaluates the five individual models — a de-vigged
bookmaker-implied baseline (the benchmark to beat), Elo, logistic, XGBoost,
Poisson — on Brier score, log loss, accuracy, ECE, and a paper-staking
simulation. Calibration and ensembling are applied in the production
training/recommendation path, not (yet) inside the backtest runner.

**Verified results (reproducible from this repo).**
- 313 automated tests passing (1 by-design skip), including migration
  smoke test on a fresh database, API route contracts, leakage/split
  assertions, and metric implementations.
- `alembic upgrade head` builds the full schema from an empty database.
- The pipeline and live-readiness gate run end-to-end; the gate correctly
  reports `not_ready` given the current (empty) betting history.

**Important limitations (stated deliberately).**
- **No claim that any model beats bookmaker prices.** The one recorded
  bookmaker-baseline comparison (`ACCURACY_PLAN.md`, 2026-04-10) was computed
  with ~0% odds coverage in training data and is not a valid market
  comparison.
- Historical metric snapshots (e.g. logistic Brier 0.183 / 69% accuracy) are
  unreproduced: the repository bundles no dataset, database, or
  backtest-result artifacts; regenerating them requires re-ingesting external
  data.
- The paper-trading log is empty — zero recorded paper-trading outcomes.
- Historical weather features use Open-Meteo *observed* kickoff conditions,
  not the forecast that would have been available pre-match — a documented
  look-ahead exception that can make backtests using weather features
  optimistic and creates train/serve skew versus live forecasts.
- The backtest runner covers the individual models only; the calibrated
  ensemble used in production recommendations has not been backtested.
- Single-market scope (H2H only), free-tier data sources, no closing-line
  movement modelling in the backtest simulation.

**30-second interview version.** "AFL Predict is a research system I built to
test whether machine-learned models can find value against bookmaker prices
in Australian football. It's the full quant pipeline — data ingestion from
four public APIs, eleven leakage-controlled feature extractors, an ensemble
of Elo, logistic, XGBoost and Poisson models with isotonic calibration,
Kelly-capped paper staking, and a walk-forward backtest framework — wrapped
in a FastAPI service with a React dashboard and a live-readiness gate. The
honest headline is the engineering and the evaluation discipline, not a
profit claim: the system is paper-trading only, and I document exactly which
results are verified and which aren't — including why my early
'model-beats-bookmaker' numbers were an artifact of missing odds data."
