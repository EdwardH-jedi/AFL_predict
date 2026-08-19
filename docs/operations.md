# Operations

Running the system on a schedule. For a one-off local run see the top-level
`README.md`; for architecture see [`architecture.md`](architecture.md).

> **Paper trading only.** Nothing in this document places a bet. `notify_bets`
> posts a Discord message; `tab_tracking` records bets a human already placed
> elsewhere. No component holds bookmaker credentials or contacts a sportsbook.

---

## The daily pipeline

```bash
make pipeline                                   # triggered_by=manual
python -m orchestration.daily_pipeline --triggered-by cron
```

`orchestration/daily_pipeline.py` runs jobs in dependency order, writes a
`pipeline_runs` row per job, and records the whole run in
`daily_pipeline_runs`.

| Order | Job | Depends on | Network |
|---|---|---|---|
| 1 | `check_data_freshness` | — | no |
| 2 | `ingest_afl` | — | Squiggle |
| 3 | `ingest_tab_odds` | — | The Odds API (skipped when `ODDS_API_KEY` is blank) |
| 4 | `fetch_weather` | fixtures | Open-Meteo |
| 5 | `build_features` | 2, 3 | no |
| 6 | `generate_recommendations` | 5 + a trained model | no |
| 7 | `notify_bets` | 6 | Discord (skipped when `DISCORD_ENABLED=false`) |
| 8 | `settle_results` | 2 | no |
| 9 | `generate_daily_summary` | all | no |
| 10 | `roles/*` audits | all | no |

Behaviour worth knowing:

- **Retries apply to network jobs only.** `PIPELINE_MAX_RETRIES` (default 2)
  with `PIPELINE_RETRY_DELAY_SECONDS` between attempts. Pure-compute jobs are
  not retried — a deterministic failure will not fix itself.
- **Hard-dependency failures skip downstream jobs.** If `build_features` fails,
  `generate_recommendations` is skipped rather than run on stale features.
  Recommendations against yesterday's data are worse than none.
- **Idempotent.** Safe to re-run the same day. Ingestion upserts; a match result
  is written once and never overwritten. Regenerating recommendations voids
  stale *pending* recommendations, but preserves any that already have a
  `BetOutcome` row, so settlement history stays intact.

Weekly, separately (it is slow and does not need to be daily):

```bash
make train-models       # 5 models + calibration, writes ModelRun rows + artifacts
make backtest           # walk-forward evaluation
```

---

## Single-machine schedule

### Linux / macOS (cron)

```cron
# Fixtures, odds, features, recommendations, notify, settle — daily 08:00
0 8 * * *  cd /srv/afl_predict && .venv/bin/python -m orchestration.daily_pipeline --triggered-by cron >> logs/pipeline_cron.log 2>&1

# Retrain weekly, Monday 03:00
0 3 * * 1  cd /srv/afl_predict && .venv/bin/python -m orchestration.jobs.train_models >> logs/train.log 2>&1
```

A worked example is in [`../ops/crontab_server.txt`](../ops/crontab_server.txt).

### FastAPI as a service (Linux)

`/etc/systemd/system/afl-predict.service`:

```ini
[Unit]
Description=AFL Predict API
After=network.target postgresql.service

[Service]
Type=simple
User=afl
WorkingDirectory=/srv/afl_predict
ExecStart=/srv/afl_predict/.venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now afl-predict
```

`systemctl` is Linux-only. On Windows use Task Scheduler or NSSM.

### Windows (Task Scheduler)

Batch and PowerShell wrappers that resolve the project root from their own
location live in [`../ops/windows_tasks/`](../ops/windows_tasks/):

| Script | Purpose |
|---|---|
| `run_daily_pipeline.bat` / `.ps1` | Daily pipeline |
| `run_weekly_train.bat` | Weekly retrain |
| `run_fetch_weather.bat` | Weather ingestion |
| `start_api_server.bat` | FastAPI on startup |
| `register_tasks.ps1` | Registers the above as scheduled tasks |

```powershell
powershell -ExecutionPolicy Bypass -File .\ops\windows_tasks\register_tasks.ps1
```

Use `-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable)` so a task
missed while the machine was off runs after boot instead of being skipped.

---

## Two-machine deployment

The author runs this across two Windows machines sharing one PostgreSQL
database. `NODE_ROLE` in `.env` decides which jobs each machine runs.

| Machine | `NODE_ROLE` | Uptime | Responsibilities |
|---|---|---|---|
| RX 6600 desktop | `collector` | 24/7 | PostgreSQL host, FastAPI :8000, ingestion (fixtures, odds, weather) |
| RTX 5080 desktop | `predictor` | On demand | Feature build, inference, recommendations, Discord notify, weekly CUDA training |
| Single machine | `standalone` | — | Everything (the default) |

`daily_pipeline.py` filters its job list by `NODE_ROLE`, so the same codebase and
the same command run on both machines.

Consequences of the split:

- **The collector is a single point of failure.** It hosts the database and the
  API. If it is off, nothing works — disable sleep on it.
- **The predictor is optional day to day.** With it off, ingestion and the
  dashboard keep working, but no recommendations, notifications or settlements
  are produced for that day.
- **The only shared state is PostgreSQL.** Model artifacts and parquet files stay
  local to the predictor; only `Prediction` and `Recommendation` rows cross over.
  Restoring the predictor from scratch means retraining, not copying files.

**The canonical schedule, failure modes, and setup steps are in
[`../ops/orchestration_24_7.md`](../ops/orchestration_24_7.md) and
[`../ops/machine_workflows.md`](../ops/machine_workflows.md)** (both written in
Korean). Where any schedule in another document or script disagrees,
`orchestration_24_7.md` wins.

---

## Configuration

All settings come from environment variables or `.env`, typed and validated by
`config/settings.py`. Copy `.env.example` and edit. Nothing is required for
local work — the defaults give SQLite, no odds ingestion, and no Discord.

| Variable | Default | Notes |
|---|---|---|
| `DB_URL` | `sqlite:///./afl_predict.db` | PostgreSQL: `postgresql+psycopg2://user:pass@host:5432/afl_predict` |
| `NODE_ROLE` | `standalone` | `collector` / `predictor` for the split above |
| `ODDS_API_KEY` | *(blank)* | Blank disables live odds ingestion. Everything else still runs. |
| `DISCORD_ENABLED` | `false` | Master switch for alerts |
| `MIN_EDGE_THRESHOLD` | `0.03` | Minimum edge to recommend |
| `MAX_KELLY_FRACTION` | `0.05` | Hard stake cap. Do not raise casually. |
| `ENSEMBLE_WEIGHT_*` | see `.env.example` | Single source of truth for the blend |
| `READINESS_*` | see `.env.example` | Live-readiness gate thresholds |

**Secrets stay in `.env`, which is gitignored.** Do not commit credentials.
Changing recommendation parameters is not a casual edit — see
[`recommendation_quality_iteration.md`](recommendation_quality_iteration.md).

---

## Monitoring

```bash
make freshness-check     # are odds and fixtures stale?
make today-summary       # today's pipeline artifact
make readiness           # live-readiness gate
make clv                 # closing-line value across settled bets
```

The dashboard's status banner reports data freshness, readiness, Discord
reachability and which data source was actually overlaid.

### Live-readiness gate

`evaluation/live_readiness.py` checks settled sample size, drawdown, calibration
error, recent job failures, and outstanding blockers, returning
`ready` / `marginal` / `not_ready`.

**A `ready` verdict authorises nothing.** It is decision support. Moving to real
money is a manual human decision taken outside this repository, and the codebase
has no mechanism to place a bet regardless of what the gate says.

---

## Runbooks

| Situation | Document |
|---|---|
| Routine day | [`ops_daily.md`](ops_daily.md) |
| Full operator reference | [`operator_runbook.md`](operator_runbook.md) |
| Pipeline failed | [`ops_failed_pipeline.md`](ops_failed_pipeline.md) |
| Data looks stale | [`ops_stale_data.md`](ops_stale_data.md) |
| Considering a live trial | [`ops_live_readiness.md`](ops_live_readiness.md) |
| Weekly review | [`weekly_review_framework.md`](weekly_review_framework.md) |
| 30-day review | [`ops_30day_review.md`](ops_30day_review.md) |
| Paper-trading plan | [`paper_trading_operation_plan.md`](paper_trading_operation_plan.md) |
| Changing thresholds | [`recommendation_quality_iteration.md`](recommendation_quality_iteration.md) |
