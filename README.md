# AFL Predict

A historical/backtesting **research system** for AFL (Australian Rules
Football) head-to-head match prediction, run paper-trading-first.
**There is no live-money betting automation anywhere in this codebase** —
recommendations are analytics and Discord alerts only, and every
recommendation is hard-coded `paper_trade=True`.

**Central research question:** can a calibrated ensemble of statistical
models (Elo, logistic regression, XGBoost, Poisson) extract predictive
signal beyond public bookmaker prices on AFL H2H markets — measured by
Brier score, log loss, calibration (ECE), and Closing Line Value on a
leakage-controlled, walk-forward backtest?

**Stack:** Python 3.11 · FastAPI · SQLAlchemy 2 + Alembic (SQLite/PostgreSQL)
· scikit-learn / XGBoost / statsmodels · pandas + pyarrow · pytest + ruff
· React/TypeScript dashboard.

## Current status

- **Code verified:** 313 tests passing (1 by-design skip), Alembic migration
  chain builds a fresh database from scratch, daily pipeline and readiness
  gate run end-to-end.
- **Research results: preliminary, not reproducible from this repo alone.**
  No dataset or backtest artifacts are bundled; historical metric snapshots
  in `ACCURACY_PLAN.md` carry explicit caveats. In particular, **no claim is
  made that any model beats bookmaker prices** — the recorded bookmaker
  baseline was computed with ~0% odds coverage and is not a valid market
  comparison.
- The paper-trading log is empty (no live-trial results yet), and the
  live-readiness gate correctly reports `not_ready`.
- Verification evidence and remaining limitations:
  `docs/T6_MERGE_READINESS.md`. Concise summary for reviewers:
  `docs/PORTFOLIO_FACTS.md`.

## Architecture

```text
collectors/     raw data ingestion
features/       feature engineering
models/         prediction and calibration models
evaluation/     model scoring and readiness checks
orchestration/  daily pipeline jobs
api/            FastAPI service and dashboard endpoints
db/             SQLAlchemy models and migrations
config/         environment-based settings
tests/          unit and integration tests
storage/        summaries, artifacts, and local outputs
```

## Quick start (Linux)

```bash
cp .env.example .env
bash bootstrap.sh
python -m alembic upgrade head        # create / migrate the DB
make serve
make pipeline
make test
```

## Fresh-clone setup

The project ships with a chain of Alembic migrations that builds the
schema from an empty database. Migration `0000_initial_schema.py` creates
the base tables; later migrations evolve them. **Run `alembic upgrade
head` before anything else** — the API, pipeline, and tests all expect
the schema to already exist.

> `make db-init` (which calls `Base.metadata.create_all`) is kept for
> ad-hoc inspection only. Do not mix it with `alembic upgrade head` on
> the same database — the two paths produce overlapping DDL and will
> collide. Pick one. For everything except a quick throwaway,
> `alembic upgrade head` is the right choice.

### Windows (local development)

```powershell
# 1. Clone
git clone <repo-url> AFL_predict
cd AFL_predict

# 2. Virtualenv + dependencies (Python 3.11)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

# 3. Environment file
copy .env.example .env
# edit .env if you need real Odds API / Discord credentials

# 4. Build the database (SQLite by default — afl_predict.db in the repo root)
python -m alembic upgrade head

# 5. Run the API
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 6. Verify it is healthy (separate terminal)
curl http://localhost:8000/health
```

> `systemctl` is a Linux init system and is **not** available on
> Windows. To run the API as a background service on Windows, use the
> Task Scheduler or NSSM instead.

### Linux (server / production-ish)

```bash
# 1. Clone
git clone <repo-url> AFL_predict
cd AFL_predict

# 2. Virtualenv + dependencies (Python 3.11)
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

# 3. Environment file
cp .env.example .env
# edit .env for production DB_URL, ODDS_API_KEY, DISCORD_WEBHOOK_URL, ...

# 4. Build / migrate the database
python -m alembic upgrade head

# 5. Run the API (foreground)
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 6. Health check
curl http://localhost:8000/health
```

To run as a managed service on Linux, install a unit file at
`/etc/systemd/system/afl-predict.service` and use:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now afl-predict
sudo systemctl status afl-predict
```

(`systemctl` is Linux-only — do not run these on Windows.)

### Smoke-test the migration chain

```bash
python -m pytest tests/test_alembic_fresh_db.py -v
```

This creates a throwaway SQLite database in a temp directory, runs
`alembic upgrade head` against it, and asserts that the core tables
(`matches`, `teams`, `predictions`, `recommendations`, `model_runs`,
`bet_outcomes`, `bankroll_logs`) all exist. It never touches
`afl_predict.db` or any production database.

## Review guidance

- Keep source changes separate from generated artifacts under `logs/`, `reviews/`, and `storage/`.
- Re-run training, backtesting, and readiness checks on the final intended tree before merge.
- Confirm dual-machine environment settings in `.env.example` before release or operator handoff.
- See `docs/T6_MERGE_READINESS.md` for the verification closeout record and standing limitations.
