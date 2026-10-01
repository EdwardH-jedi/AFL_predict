# AFL Predict

AFL Predict is a paper-trading research system for Australian Rules Football head-to-head match prediction. It brings together data collection, time-aware features, statistical models, walk-forward evaluation, and a FastAPI service with a local dashboard.

The research question is whether model probabilities add information beyond public bookmaker prices. **This repository does not establish that they do.** Recommendations are paper-only analytics; the code does not place live-money wagers.

[Local setup](#local-setup) · [Research evidence and limitations](docs/PORTFOLIO_FACTS.md) · [Backtesting method](docs/backtesting.md) · [CI](https://github.com/EdwardH-jedi/AFL_predict/actions/workflows/ci.yml)

## Status and what to review

This is a research and engineering project, not a validated betting product. Historical performance snapshots cannot be reproduced from the repository alone because the underlying datasets, database, and backtest outputs are not bundled. The documented paper-trading history has no outcomes, and the recorded readiness assessment is `not_ready`.

Useful entry points:

- [Temporal splits](backtesting/splits.py) and [split tests](tests/test_splits.py) show how training-before-test order is enforced
- [Backtesting documentation](docs/backtesting.md) explains the evaluation, weather exception, and simulation limits
- [Readiness checks](evaluation/live_readiness.py) identify missing operational evidence
- [Verification closeout](docs/T6_MERGE_READINESS.md) records earlier checks and limitations; use the CI run for a particular commit to establish its regression-test status

## Implemented scope

- **Data ingestion:** collectors for AFL fixtures/results, bookmaker odds snapshots, weather, and player statistics
- **Feature engineering:** pre-match feature construction with timestamp checks and temporal train/test splits
- **Models:** bookmaker-implied baseline, Elo, logistic regression, XGBoost, and Poisson; calibration and weighted ensembling in the training/recommendation path
- **Evaluation:** expanding/rolling walk-forward backtests for individual models, Brier score, log loss, calibration error, and paper-staking simulation; separate Closing Line Value tracking
- **Paper operations:** recommendation generation with capped simulated stakes and abstention rules, pipeline retries, freshness checks, daily summaries, and a readiness report
- **API and UI:** fixture, prediction, recommendation, and dashboard endpoints; optional Discord alerts/history and collector/predictor node roles

Recommendation generation hard-codes `paper_trade=True`. Keep `PAPER_TRADE_ONLY=true`; changing an environment value does not turn this into a validated wagering system.

## Stack and architecture

| Area | Implementation |
| --- | --- |
| Backend | Python 3.11, FastAPI, Pydantic settings, SQLAlchemy 2, Alembic |
| Database | SQLite for local development; PostgreSQL configuration supported |
| Research | pandas, pyarrow, scikit-learn, XGBoost, statsmodels |
| Served dashboard | React/JSX static assets mounted by FastAPI, with CDN-loaded runtime dependencies |
| Experimental frontend | Separate React/TypeScript/Vite workspace in `frontend/` |
| Checks | pytest and local Ruff tooling; current CI runs the Python regression suite |

Data flows from `collectors/` through `features/` and `models/`, then into predictions, paper recommendations, evaluation, and API responses. `orchestration/` coordinates jobs and summaries. Alembic owns database schema changes.

## Local setup

Use a local, disposable development environment. **Keep the API bound to loopback:** TAB tracking routes currently need access-control and transaction hardening before any shared or public deployment. Do not assume that an API secret or CORS settings protect those routes.

Prerequisites: Git and Python 3.11. The served dashboard does not require a Node build, but its React/Babel scripts and fonts require internet access.

### 1. Create the environment

Linux/macOS with Bash:

```bash
git clone https://github.com/EdwardH-jedi/AFL_predict.git
cd AFL_predict
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

On Windows PowerShell, use `py -3.11 -m venv .venv`, activate with `.\.venv\Scripts\Activate.ps1`, and use `Copy-Item .env.example .env`. The remaining `python -m ...` commands are the same.

For this local preview, set these values in `.env`:

```dotenv
DB_URL=sqlite:///./afl_predict.db
PAPER_TRADE_ONLY=true
ODDS_API_KEY=
DISCORD_ENABLED=false
DISCORD_WEBHOOK_URL=
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=
```

This clears the example Odds API placeholder and leaves external messaging disabled. Keep `.env` out of version control. The template's API secret is a development placeholder, not a production credential or an access-control guarantee. Review the [settings](config/settings.py) and [environment template](.env.example) before enabling integrations.

### 2. Migrate and start the API

From the repository root with the virtual environment active:

```bash
python -m alembic upgrade head
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

Use Alembic for an empty database and later schema changes. Do not combine `make db-init` / `Base.metadata.create_all` with Alembic on the same database: their overlapping DDL can collide. `make db-init` is only for separate throwaway inspection.

In another terminal:

```bash
curl http://127.0.0.1:8000/health
```

Open:

- [Quant Dashboard](http://127.0.0.1:8000/static/quant-dashboard/index.html)
- [API documentation](http://127.0.0.1:8000/docs)

Starting the API does not populate research data or run the daily ingestion pipeline. Empty API responses are expected on a fresh database.

### Dashboard provenance

The recommended preview is `static/quant-dashboard/`, served by FastAPI. It initially renders synthetic demonstration data and selectively overlays available API data. **A `LIVE DATA` badge does not mean every card or chart is backed by real observations.** Some KPI values and chart series remain synthetic fallbacks. Treat the UI as a prototype, not performance evidence, and inspect the underlying API/artifacts before interpreting numbers.

The dashboard currently targets a wide desktop layout. `frontend/` is a separate experimental Vite app whose entry point is a JSON-oriented scaffold; its other page components are not all connected. It is not the dashboard served at the URL above. Its scripts live in [`frontend/package.json`](frontend/package.json).

## Tests and verification

With the Python environment active, from the repository root:

```bash
python -m pytest -q
python -m pytest tests/test_alembic_fresh_db.py -v
python -m ruff check .
```

The migration smoke test creates a temporary SQLite database and checks the Alembic chain and core tables; it does not migrate your working database. The broader suite covers API contracts, split/leakage assertions, metric implementations, and other regression behavior.

The [current CI workflow](.github/workflows/ci.yml) runs pytest on Python 3.11 with an in-memory SQLite configuration. It does not run research ingestion/training, send Discord alerts, or establish predictive performance. Ruff is a separate local check. Static-dashboard tests check asset responses and content, **not browser JavaScript execution**; CI does not currently build/test the Vite UI or establish UI correctness and end-to-end TAB persistence.

## Research limits

1. **No valid market-outperformance result is established.** The historical bookmaker comparison had approximately zero odds coverage. Missing odds can fall back to probability 0.5, which is not a market quote. Any future market comparison needs actual timestamped prices, reported coverage, and the same eligible matches for every model.
2. **Individual-model backtests do not validate the final ensemble.** Calibration and weighted ensembling are used in recommendation generation but are not yet evaluated through the same walk-forward backtest path.
3. **Historical weather has look-ahead risk.** The feature path uses observed kickoff conditions rather than forecasts available before a match, creating an optimistic evaluation risk and train/serve mismatch. See the explicit exception in [Backtesting](docs/backtesting.md).
4. **Reproduction needs external inputs.** Historical numbers in [ACCURACY_PLAN.md](ACCURACY_PLAN.md) are preliminary snapshots. A defensible comparison needs a versioned dataset/acquisition record, temporal splits, feature cutoffs, model configuration, per-match predictions, and aggregate metrics. None of the demo dashboard numbers fill that gap.
5. **Scope is limited.** Research focuses on H2H markets and available data sources; the backtest simulation does not model closing-line movement. Readiness checks and simulated returns are not proof of profitable real-world execution.

## Operations and development notes

The local preview above deliberately stops before ingestion or notifications. To work on the research pipeline, start with the [operator runbook](docs/operator_runbook.md), [ingestion guide](docs/ingestion.md), [daily operations](docs/ops_daily.md), and [paper-trading operation plan](docs/paper_trading_operation_plan.md). The [Makefile](Makefile) lists job commands, including `pipeline`, `build-features`, `train-models`, `backtest`, and `readiness`.

- Pipeline/ingestion jobs can contact external providers, consume quotas, and write data/artifacts. Notification jobs can post to configured Discord destinations. Review configuration and the command's scope before running either.
- TAB tracking is a manual record-keeping surface, not a bookmaker execution integration. Its current write paths need explicit transaction completion and access control; a success response alone should not be treated as evidence of durable saved records. Use disposable data and verify persistence independently.
- Keep generated `logs/`, `reviews/`, and `storage/` outputs separate from source edits. Rerun relevant training, backtesting, and readiness checks on the intended final tree when changing research behavior.
- Collector/predictor deployment is configured through `NODE_ROLE` and related settings. See [machine workflows](ops/machine_workflows.md), [setup guidance](docs/setup_guide.md), and the [readiness runbook](docs/ops_live_readiness.md). Linux `systemctl` instructions do not apply to Windows.
- `bootstrap.sh` installs the Python environment, but its activation does not persist in the calling shell; activate `.venv` before subsequent commands. Its suggested `make serve` binds all interfaces, so use the loopback command above for local review.

## Repository map

| Path | Contents |
| --- | --- |
| [`collectors/`](collectors/) | External data adapters |
| [`features/`](features/) | Feature extraction and time-cutoff rules |
| [`models/`](models/) | Baselines, calibration, and ensemble code |
| [`backtesting/`](backtesting/) | Splits, runner, metrics, and paper simulation |
| [`evaluation/`](evaluation/) | Scoring, CLV, and readiness checks |
| [`orchestration/`](orchestration/) | Daily pipeline and individual jobs |
| [`api/`](api/) | FastAPI application and routes |
| [`db/`](db/) | SQLAlchemy models, sessions, and migrations |
| [`static/quant-dashboard/`](static/quant-dashboard/) | Served prototype dashboard |
| [`frontend/`](frontend/) | Experimental Vite app |
| [`config/`](config/), [`tests/`](tests/), [`docs/`](docs/), [`ops/`](ops/) | Settings, regression tests, research documentation, and runbooks |
| [`storage/`](storage/) | Local summaries, model artifacts, and research outputs |

## License

No license file is included in this repository. No open-source reuse license is declared; contact the owner before reusing or redistributing the code.
