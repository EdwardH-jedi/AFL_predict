# AFL Predict

**An end-to-end machine-learning AFL forecasting and paper-trading research platform.**

> This repository performs **analytics and paper trading only**. It contains no
> automated real-money betting execution, holds no bookmaker credentials, and
> has no code path that places a wager.

[![CI](https://github.com/EdwardH-jedi/AFL_predict/actions/workflows/ci.yml/badge.svg)](https://github.com/EdwardH-jedi/AFL_predict/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

![AFL Predict dashboard showing the sample-data banner and model predictions for a held-out round](docs/assets/prediction-view.png)

*Output of `make demo`: for each match in a held-out round, the ensemble's
probability, the market's implied probability, and the resulting edge. **Every
row in the table comes from the demo run**; the filter bar above it is static
chrome from the design handoff. [Asset notes](docs/assets/README.md) list exactly
which parts of this dashboard are data and which are placeholder.*

---

## Overview

Forecasting AFL match outcomes as **calibrated probabilities**, and answering
honestly whether those probabilities are better than the market's.

The difficult part is not fitting a classifier. It is building an evaluation you
can trust: sports data is a time series where the obvious way to compute "team
form" silently includes the match being predicted, and where a model that
appears to beat the closing market is far more likely to be leaking than to be
skilful.

**The headline result is that the models do not beat the bookmaker consensus.**
That is the credible outcome for a liquid market, and this project's value is in
having measured it correctly rather than in having beaten it.

---

## What it does

- **Collects** fixtures, results, bookmaker odds, weather and player data from
  public APIs, snapshotting every raw response before parsing
- **Builds leakage-safe pre-match features** — Elo, rolling form, momentum,
  head-to-head, venue, rest, interstate travel, market prices
- **Trains five probabilistic models** — Elo, logistic regression, XGBoost, a
  Poisson score baseline, and a bookmaker-consensus benchmark
- **Calibrates** forecasts with out-of-sample isotonic regression
- **Ensembles** them under a single authoritative weight configuration
- **Evaluates** with expanding-window walk-forward backtesting, asserting
  temporal ordering rather than assuming it
- **Simulates paper-trading decisions** with Kelly staking under a hard cap
- **Exposes** results through FastAPI endpoints and a dashboard
- **Runs on a schedule**, with retries on network steps and per-job audit records

---

## System pipeline

```text
  Squiggle API · The Odds API · Open-Meteo
                    │
                    ▼
  collectors/       collect → parse → validate → transform → upsert
                    │
                    ▼
  db/               PostgreSQL / SQLite  (SQLAlchemy + Alembic)
                    │
                    ▼
  features/         one row per match, strictly pre-match values
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  models/                  backtesting/
  Elo · Logistic ·         expanding-window folds,
  XGBoost · Poisson ·      leakage assertions,
  Bookmaker baseline       Brier · log loss · ECE,
        │                  staking simulation
        ▼
  calibration → ensemble
        │
        ▼
  orchestration/    edge vs market → capped Kelly → paper recommendations
        │
   ┌────┴─────┬─────────────┬──────────────┐
   ▼          ▼             ▼              ▼
 FastAPI   dashboard   Discord alert   readiness · CLV
```

See [Architecture](docs/ARCHITECTURE.md) for component detail and real paths.

---

## Models / methods

| Model | Role |
|---|---|
| **Bookmaker consensus** | The benchmark to beat. Deliberately *not* an ensemble component. |
| **Elo** | Ratings with home advantage and between-season regression. |
| **Logistic regression** | L2-regularised over 29 features. Strongest single model here. |
| **XGBoost** | Gradient-boosted trees. Weakest of the three trained learners out of sample. |
| **Poisson** | Currently conditioned only on an intercept and finals status — a global baseline, not a match-specific model. |
| **Ensemble** | Weighted average from `Settings.ensemble_weights`, one authoritative source. |

Feature engineering, the leakage argument, calibration flow and validation design
are in [Methodology](docs/methodology.md).

---

## Evaluation

Expanding-window walk-forward, 7 test seasons (2019–2025), **1,413 settled
matches**, untuned model defaults.

| Model | Brier ↓ | Log loss ↓ | Accuracy ↑ | ECE ↓ |
|---|---|---|---|---|
| **Bookmaker consensus** (benchmark) | **0.1997** | **0.5811** | **68.6%** | **0.0678** |
| Logistic regression | 0.2056 | 0.5961 | 67.7% | 0.0871 |
| Ensemble | 0.2081 | 0.6033 | 67.4% | 0.0824 |

*Brier 0.25 = coin flip. Always picking the home team scores 56.8% on these
matches.*

**No model beats the market.** The benchmark wins all four metrics in aggregate
and wins Brier and log loss in every one of the seven test seasons. The best
model is about 3% worse on Brier.

Full tables, per-season breakdown, staking simulation, negative results and
limitations: **[Results](docs/RESULTS.md)**.

---

## Architecture

See **[Architecture](docs/ARCHITECTURE.md)**.

## Current status

Research project — tested, evaluation re-runs to a committed artifact, not deployed.
See **[Project Status](docs/PROJECT_STATUS.md)**.

---

## Running locally

Requires Python 3.11. Nothing below needs a credential.

```bash
git clone https://github.com/EdwardH-jedi/AFL_predict.git
cd AFL_predict
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

make demo                          # ~30s, no .env, database or network
```

`make demo` reads `examples/sample_matches.csv` (636 real completed matches,
2023–2025), holds out the last home-and-away round, trains the real models on
everything earlier, applies the real Kelly staking rule, and writes the dashboard
payload. Then:

```bash
python serve.py                    # http://localhost:8080
```

For the full stack:

```bash
cp .env.example .env               # local-only defaults: SQLite, no keys
python -m alembic upgrade head     # build the schema — do this before anything else
make serve                         # FastAPI on :8000
```

`alembic upgrade head` is the only supported way to create the schema.
`make help` lists every target. Scheduled operation, the dual-machine deployment
and configuration reference: [Operations](docs/operations.md).

---

## Reproducing the evaluation

Needs network access to the Squiggle API (free, no key); about 5 minutes.

```bash
python -m alembic upgrade head          # required before ingestion
for y in 2017 2018 2019 2020 2021 2022 2023 2024 2025; do
  python -m orchestration.jobs.ingest_afl --season $y
done
python -m orchestration.jobs.backfill_squiggle_odds
python -m orchestration.jobs.build_features
python -m orchestration.jobs.run_backtest --min-season 2017 --max-season 2025 --untuned
```

`--untuned` is not optional for publishable numbers: the tuners search the same
folds that get reported. The exact artifact behind every published figure is
committed as [`examples/backtest_2026-08-19.json`](examples/backtest_2026-08-19.json).

Testing:

```bash
make test      # pytest tests/ -v          (345 tests)
make lint      # ruff check .
```

---

## Repository structure

```text
collectors/      ingestion: collect → parse → validate → transform → upsert
features/        extractors + DatasetBuilder → one row per match
models/          Elo, logistic, XGBoost, Poisson, bookmaker baseline, ensemble
backtesting/     walk-forward splits, metrics, staking simulation, artifacts
evaluation/      readiness gate, CLV tracker, scoring
orchestration/   daily pipeline and jobs
api/             FastAPI service (9 routers)
db/              SQLAlchemy models + Alembic migrations
static/          canonical dashboard (quant-dashboard/)
frontend/        secondary Vite/React app
demo/            credential-free portfolio demo
examples/        bundled sample data + committed result artifact
docs/            documentation (see below)
ops/             machine-specific scheduling scripts and runbooks
tests/           pytest suite
```

---

## Limitations

- **The models do not beat the bookmaker consensus.**
- Historical data only; no live or forward-tested period has been measured.
- Simulated ROI uses margin-free consensus prices, so it is structurally
  optimistic and is not evidence of profitability.
- No bootstrap confidence intervals for the canonical run — no result carries a
  significance claim.
- Player-availability and weather features are constant or null and contribute nothing.
- **Eight of nine API routers have no authentication** (only `/api/sync/*` checks
  a shared-secret header), and `make serve` binds `0.0.0.0`; the `/api/tab/*`
  routes mutate the paper-trading ledger. Safe on a trusted LAN only.
- Evaluation is inspectable but not bit-reproducible from a clean clone.
- The static dashboard is a design prototype; unfed panels show placeholder values.

Full list with detail: [Results §14](docs/RESULTS.md#14-limitations) and
[Project Status §9](docs/PROJECT_STATUS.md#9-known-issues).

---

## Documentation

| Document | Contents |
|---|---|
| [Project Status](docs/PROJECT_STATUS.md) | What exists, what works, validation results, known issues |
| [Results](docs/RESULTS.md) | Measured evaluation evidence, negative results, verified and unsupported claims |
| [Architecture](docs/ARCHITECTURE.md) | Components, data flow, engineering decisions |
| [Portfolio Facts](docs/PORTFOLIO_FACTS.md) | Claims verified as safe for external use |
| [Methodology](docs/methodology.md) | Features, leakage prevention, calibration, validation |
| [Operations](docs/operations.md) | Scheduling, dual-machine deployment, configuration |
| [docs/archive/](docs/archive/README.md) | Historical plans — not current specifications |

---

## Responsible use

**Paper trading only. No automatic real-money bet placement.**

- Every recommendation is written with `paper_trade = True`.
- `notify_bets.py` posts a Discord message. That is the entire notification path.
- `tab_tracking.py` records bets a human placed elsewhere, for audit. It holds no
  bookmaker credentials and contacts no sportsbook.
- `evaluation/live_readiness.py` reports whether accumulated evidence *would*
  support a restricted live trial. A `ready` verdict authorises nothing; there is
  no mechanism in this codebase to act on it.
- Betting carries real financial risk. Nothing here is financial advice, and the
  measured results are a poor case for wagering money.

---

## License

MIT — see [`LICENSE`](LICENSE).
