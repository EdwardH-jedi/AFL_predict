# Project Status

**Last verified:** 2026-08-21
**Repository:** EdwardH-jedi/AFL_predict
**Default branch:** `main`
**Status:** Research

---

## 1. Project summary

An end-to-end AFL (Australian Football League) match-forecasting and
paper-trading research platform. It ingests fixtures, results, bookmaker odds and
contextual data from public APIs; engineers leakage-safe pre-match features;
trains and calibrates several probabilistic models; evaluates them with
expanding-window walk-forward backtesting against a bookmaker-consensus
benchmark; and generates simulated (paper) value-betting recommendations exposed
through a FastAPI service and a dashboard.

**It performs analytics and paper trading only.** No component places a wager,
holds bookmaker credentials, or contacts a sportsbook.

---

## 2. Current stage

**Reproducible backtesting and research system**, operated locally / on a private
LAN.

More precisely: the modelling and evaluation half is complete and tested, and
re-running the documented command reproduces the committed artifact exactly from
the local feature set. It is **not** bit-reproducible from a clean clone (§7). The operational half (scheduled ingestion, recommendation generation,
Discord alerting) is implemented and has been run, but the accumulated
paper-trading record is not yet large enough to report outcome statistics.

It is *not* a production service and *not* a deployed product.

---

## 3. Implemented

### Data
- Squiggle API ingestion — fixtures, results, teams (`collectors/afl_collector.py`, `collectors/squiggle_collector.py`). Free, public, no key.
- Historical bookmaker-consensus odds backfill (`orchestration/jobs/backfill_squiggle_odds.py`), with source-provenance tagging.
- The Odds API live H2H odds (`collectors/odds_api_collector.py`) — requires a key; skipped when blank.
- Open-Meteo weather (`collectors/weather_collector.py`), player data (`collectors/player_collector.py`), FootyWire odds scrape (`collectors/footywire_odds_collector.py`).
- Five-stage ingestion contract: collect → parse → validate → transform → upsert. Raw payloads snapshotted before parsing (`collectors/snapshot_store.py`).
- Idempotent upserts keyed on `external_id`; match results written once and never overwritten.

### Feature engineering
- `features/feature_builder.py` composes independent extractors under `features/extractors/`: Elo, form, head-to-head, venue, venue performance, rest, travel, bookmaker, odds movement, weather, player availability.
- 29 feature columns consumed by the logistic and XGBoost models.
- Output persisted to parquet and the `match_features` table.
- Leakage rule enforced per extractor and asserted in tests.

### Prediction models
- Bookmaker baseline (benchmark), Elo, logistic regression, XGBoost, Poisson.
- Weighted ensemble with a single authoritative weight source (`Settings.ensemble_weights`).
- All implement a common `BaseModel` interface, so trainer, backtester and recommender are model-agnostic.

### Calibration
- `models/calibrated_model.py` — post-hoc isotonic regression, fitted out-of-sample on a held-out season. Applied to logistic and XGBoost in the production training flow.

### Backtesting
- Expanding and rolling walk-forward splits with a leakage assertion that raises (`backtesting/splits.py`).
- Brier, log loss, accuracy, ECE, plus staking simulation and settlement (`backtesting/metrics.py`, `simulation.py`).
- Bootstrap confidence intervals available (`backtesting/bootstrap.py`) — implemented but not computed for the current canonical run.
- Result artifacts serialised to JSON (`backtesting/artifacts.py`).

### API
- FastAPI service with 9 routers: health, fixtures, predictions, recommendations, dashboard, dashboard-ui, sync, TAB tracking, Discord history (`api/main.py`).

### Notifications / automation
- Discord webhook alerts for value picks (`orchestration/jobs/notify_bets.py`) — alerts only.
- `orchestration/daily_pipeline.py` sequences 13 jobs with retries on network steps and per-job run records. It has a hard-dependency mechanism, but see §9 — it does not gate as broadly as intended.
- Role-based daily audit jobs (`orchestration/jobs/roles/`).
- Scheduling via cron / Windows Task Scheduler wrappers (`ops/`).

### Persistence
- SQLAlchemy 2.0 models with an Alembic migration chain from empty (`0000`–`0008`).
- PostgreSQL in the dual-machine deployment; SQLite by default locally.

### Testing
- 345 tests collected. Unit, contract and integration-style tests including a fresh-database migration smoke test and a node-driven dashboard transform test.
- GitHub Actions CI on push and pull request.

---

## 4. Partially implemented

| Area | State |
|---|---|
| Player availability features | Extractor and schema exist, but the historical collector hard-codes availability to 1.0 / zero absences, so the features are constant and carry no signal. Needs a pre-match team-sheet source. |
| Weather features | Extractor and schema exist; no historical weather was collected. Measurement columns are 100% null and derived flags are constant (`0` / `1.0`), so the family carries no signal. |
| Poisson model | Fits an intercept and `is_final` only, so every regular-season match receives the same probability. The class supports richer covariates; nothing supplies them. |
| Bootstrap confidence intervals | Implemented but not run for the canonical evaluation. |
| CLV tracking | `evaluation/clv_tracker.py` implemented; sample too small to report. |
| Live readiness gate | Implemented and evaluable; a `ready` verdict authorises nothing and there is no mechanism to act on it. |
| React frontend (`frontend/`) | Vite/TypeScript app covering the same endpoints; secondary to the static dashboard and not the canonical UI. |
| mypy | Configured in `pyproject.toml` and installed, but no Make target and not in CI. 49 errors currently. |

---

## 5. Not implemented

- Any real-money bet placement. Absent by design, permanently.
- Live or forward-tested performance measurement.
- ROC-AUC or any ranking metric.
- Authentication on any router other than `/api/sync/*`.
- Cloud deployment, containerisation, or orchestration beyond cron / Task Scheduler.
- LLM match previews or narrative generation — explicitly out of scope (see `docs/archive/`).
- A dependency lockfile.

---

## 6. Validation

All commands run from the repository root inside the project virtualenv, on
2026-08-21.

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | **Pass** — "All checks passed!" |
| Unit + integration tests | `pytest tests/ -q` | **Pass** — 344 passed, 1 skipped |
| Test collection | `pytest tests/ --collect-only -q` | 345 tests |
| Fresh-DB migration | `python -m pytest tests/test_alembic_fresh_db.py -v` | **Pass** — 1 passed |
| Dashboard semantics | `pytest tests/test_dashboard_edge_semantics.py -q` | **Pass** — 7 passed |
| Backtest smoke / metric generation | `python -m orchestration.jobs.run_backtest --min-season 2017 --max-season 2025 --untuned` | **Pass** — reproduces `examples/backtest_canonical.json` exactly |
| Demo | `make demo` | **Pass** — runs with no `.env`, database or network |
| Typecheck | `python -m mypy .` | **Fail** — 49 errors in 16 files. Configured but never enforced; not in CI and no Make target. |
| CI | `.github/workflows/ci.yml` | Runs lint, tests, fresh-DB migration, demo, and a clean-tree gate on Python 3.11. Does **not** run mypy. |

The one skipped test is skipped by design (`CRITICAL_TODOS` is empty, so the
"fails when TODOs present" case has nothing to assert).

---

## 7. Data availability

- **Source:** public APIs. Squiggle (fixtures, results, consensus odds) requires no key. Open-Meteo requires no key.
- **Raw data is not committed.** `storage/raw_snapshots/` is gitignored, as is the feature parquet.
- **External downloads required** to reproduce the evaluation from scratch: yes — steps 1–3 of the reproduction sequence in `RESULTS.md` §13 need network access to Squiggle.
- **Credentials required:** none for the core research path. `ODDS_API_KEY` (The Odds API) and Discord tokens are optional; blank values disable those jobs and everything else still runs.
- **Committed sample data:** `examples/sample_matches.csv` — 636 completed matches (2023–2025) with the full pre-match feature set, frozen from the pipeline. Enough to run `make demo` offline.
- **Committed evidence:** `examples/backtest_canonical.json` — the exact artifact behind every number in `RESULTS.md`.

---

## 8. Deployment / runtime

| Mode | State |
|---|---|
| Local development | Supported and documented. SQLite by default; no credentials needed. |
| Credential-free demo | `make demo` — no `.env`, database, network or API key. |
| Scheduled operation | Implemented. `orchestration/daily_pipeline.py` driven by cron (Linux) or Task Scheduler (Windows); wrappers in `ops/windows_tasks/`. |
| Dual-machine deployment | Implemented via `NODE_ROLE` (`collector` / `predictor` / `standalone`), sharing one PostgreSQL instance. Documented in `ops/orchestration_24_7.md`. |
| API | Runs locally or on a LAN host (`make serve`, binds `0.0.0.0:8000`). **Unauthenticated** — see §9. |
| Cloud / public deployment | Not implemented and not recommended in the current state. |

---

## 9. Known issues

1. **Most API routers have no authentication.** `/api/sync/*` requires an
   `X-Sync-Token` header matching `api_secret_key`
   (`api/routes/data_sync.py::_require_sync_token`); the other eight routers have
   no auth dependency. That includes `/api/tab/*`, which mutates tracked-bet and
   `BankrollLog` records, while `make serve` binds `0.0.0.0`. Anyone who can
   reach the port can corrupt the paper-trading ledger, and with it the ROI and
   CLV history the readiness gate depends on. No real money is reachable.
   Acceptable on a trusted LAN; not acceptable publicly.
2. **Hard-dependency gating is weaker than intended.** The guard is
   `if spec.hard_dep and hard_dep_failed`, so a job is skipped only when *it*
   carries `hard_dep=True`. Only `ingest_afl`, `ingest_tab_odds` and
   `build_features` do, and nothing hard-dep follows `build_features` — so a
   feature-build failure skips nothing and `generate_recommendations` runs
   against stale features. The intent was to gate downstream work; the
   implementation gates only the remaining critical chain.
3. **mypy is configured but never enforced** — 49 errors.
4. **Player-availability and weather features carry no signal** (§4).
5. **The Poisson model is effectively a global baseline**, not a match-specific model (§4).
6. **Evaluation is not bit-reproducible from a clean clone** — gitignored parquet, live upstream data, unpinned dependency ranges.
7. **The static dashboard is a design prototype.** Panels the data layer does not populate still display placeholder values; documented panel-by-panel in `docs/assets/README.md`.
8. **No bootstrap confidence intervals** for the canonical run, so no result carries a significance claim.

---

## 10. Technical debt

- Two dashboards (`static/quant-dashboard/` canonical, `frontend/` secondary) and a superseded third (`static/dashboard.html`).
- `frontend/` has no test runner and is not covered by CI.
- No dependency lockfile; `requirements.txt` pins ranges.
- The tuner scripts (`backtesting/elo_tuner.py`, `xgb_tuner.py`) search the same folds used for reporting, so their output is unusable for publishable metrics without a nested scheme.
- Operational runbooks in `ops/` are written in Korean while the rest of the documentation is English.
- The static dashboard's placeholder panels cannot be distinguished from real data without reading `docs/assets/README.md`.

---

## 11. Next recommended work

1. **Make hard-dependency gating do what the name implies.** Today a
   `build_features` failure skips nothing and `generate_recommendations` runs on
   stale features (§9.2). Either gate on the *upstream* job's status or mark the
   downstream consumers `hard_dep=True`.
2. **Compute bootstrap confidence intervals** for the canonical evaluation
   (`backtesting/bootstrap.py` already exists) so results can carry significance
   claims instead of being reported as bare point estimates.
3. **Close the leakage-test gap.** Eight of eleven extractors have no
   extractor-level leakage test, and the weather extractor joins on `match_id`
   without asserting `fetched_at < match_time`.
4. **Bring mypy to zero and enforce it** — add a `typecheck` target and a CI step;
   it currently reports 49 errors and runs nowhere.
5. **Make the evaluation reproducible from a clean clone** — pin a dependency
   lockfile and commit the feature parquet or a checksum of it.

## 12. Portfolio readiness

| Item | State |
|---|---|
| README | Concise front page; links to the four canonical documents rather than duplicating them. |
| Test status | 344 passed, 1 skipped; CI green on push and PR. |
| Reproducibility | Evaluation reproduces exactly from the local feature parquet; **not** bit-reproducible from a clean clone (§7, `RESULTS.md` §13). |
| Documentation | Four canonical docs (`PROJECT_STATUS`, `RESULTS`, `ARCHITECTURE`, `PORTFOLIO_FACTS`) plus subsystem deep-dives; historical plans archived under `docs/archive/` with a README stating they are not current specifications. |
| Metric provenance | Every number in `RESULTS.md` traces to `examples/backtest_canonical.json`, which is committed and embeds the match-level predictions behind each figure. Pooled metrics are recomputable from the artifact; a CI validator does so and fails on tampering. |
| Secrets | None tracked. `.env` gitignored; `.env.example` holds blank/placeholder values only. Scanned across the release range. |
| Misleading claims | Audited. The headline result is that the models do **not** beat the bookmaker; unsupported claims are listed explicitly in `RESULTS.md` §16. |
