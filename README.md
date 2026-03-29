# AFL Predict — Research System

A conservative, paper-trading-first research system for AFL head-to-head pre-match betting analysis.

> **Status:** MVP scaffold — no live betting, no real-money automation.

---

## Goals

- Ingest AFL fixtures and results daily
- Ingest TAB pre-match head-to-head odds snapshots
- Build match features and train baseline models
- Generate paper-trade recommendations with full audit trail
- Settle results and track model performance over time

---

## Architecture

```
collectors/     → raw data ingestion (AFL fixtures, TAB odds)
features/       → feature engineering from raw data
models/         → prediction models (bookmaker baseline, ELO, logistic)
evaluation/     → model scoring, calibration, profit-loss tracking
orchestration/  → daily pipeline jobs
api/            → FastAPI REST layer
db/             → SQLAlchemy models + session management
config/         → environment-based settings
tests/          → unit and integration tests
storage/        → raw snapshots and model artifacts (gitignored blobs)
```

---

## Quick Start

```bash
# 1. Copy env template
cp .env.example .env

# 2. Bootstrap environment
bash bootstrap.sh

# 3. Start API
make serve

# 4. Run daily pipeline manually
make pipeline

# 5. Run tests
make test
```

---

## Requirements

- Python 3.11+
- PostgreSQL (for production) — SQLite supported for local dev via `DB_URL` env var
- See `requirements.txt`

---

## Paper Trading First

All recommendations are logged as `paper_trade=True` by default until the system is validated.
No live betting integration exists in this codebase. See `PRD.md` for roadmap.

---

## TODO

- [ ] Wire real AFL data source (see `collectors/afl_collector.py`)
- [ ] Wire real TAB odds source (see `collectors/tab_odds_collector.py`)
- [ ] Implement feature engineering logic (see `features/feature_builder.py`)
- [ ] Validate ELO and logistic models on historical data
- [ ] Add Alembic migrations
- [ ] Add CI pipeline (GitHub Actions)
- [ ] Dashboard UI (React or Streamlit TBD)
