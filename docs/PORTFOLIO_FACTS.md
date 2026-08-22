# Portfolio Facts

**Last verified:** 2026-08-21

> Only repository-verified facts safe for external use belong here.
> Every number traces to [`RESULTS.md`](RESULTS.md) and the committed artifact
> `examples/backtest_2026-08-19.json`. Every capability claim traces to
> [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

---

## 1. Identity

| Field | Value |
|---|---|
| Project name | AFL Predict |
| Repository | EdwardH-jedi/AFL_predict |
| Project type | Applied ML / data engineering research project |
| Status | Research — active and tested; evaluation re-runs to the committed artifact, but is not bit-reproducible from a clean clone |
| Language | Python 3.11 |
| Licence | MIT |

---

## 2. One-line description

> An end-to-end sports forecasting platform that ingests public AFL data, builds
> leakage-safe features, and evaluates calibrated probability models against a
> bookmaker-consensus benchmark using walk-forward backtesting.

Secondary sentence if more room is available:

> It generates paper-trading recommendations for research purposes only and
> contains no real-money betting execution.

---

## 3. Problem

Forecasting AFL match outcomes as **calibrated probabilities**, and answering
honestly whether those probabilities are better than the market's.

The hard part is not fitting a classifier. It is building an evaluation you can
trust: sports data is a time series where the obvious way to compute "team form"
silently includes the match being predicted, and where a model that appears to
beat the closing market is far more likely to be leaking than to be skilful.

---

## 4. What I built

- Ingestion for five public data sources. The primary AFL and odds collectors
  follow a collect → parse → validate → transform → upsert contract with
  raw-payload snapshotting; the weather and FootyWire collectors are simpler and
  do not snapshot.
- A feature pipeline of 11 independent extractors producing one leakage-safe row
  per match, with the temporal rule enforced by an assertion that raises.
- Five probabilistic models behind one interface, plus out-of-sample isotonic
  calibration and a configurable weighted ensemble.
- An expanding-window walk-forward backtester reporting Brier, log loss,
  accuracy and ECE, plus a Kelly-capped staking simulation.
- A daily orchestration pipeline with retries on network steps and per-job
  audit records, deployable across two machines from one codebase.
- A FastAPI service and dashboard, a credential-free demo, and CI.

---

## 5. Technical ownership

Sole author. All areas below were designed and implemented by me.

### Data
Collectors, parsers, validators, transformers, snapshot store, team-name
normalisation, historical odds backfill with source-provenance tagging,
idempotent upserts, SQLAlchemy schema and Alembic migration chain.

### Machine learning
Feature extractors, leakage enforcement, all five models, isotonic calibration
flow, ensemble weighting, walk-forward splits, metrics (Brier / log loss /
accuracy / ECE), staking simulation, bootstrap CI implementation.

### Backend
FastAPI service (9 routers), Pydantic settings, dashboard data contract,
persistence layer.

### Automation
Daily pipeline sequencing with retry handling, dual-machine role
filtering, cron / Task Scheduler wrappers, Discord alerting, GitHub Actions CI.

---

## 6. Verified technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| API | FastAPI, Uvicorn, Pydantic v2 |
| Data | PostgreSQL / SQLite, SQLAlchemy 2.0, Alembic, pandas, NumPy, PyArrow |
| ML | scikit-learn, XGBoost, statsmodels, SciPy, SHAP |
| HTTP | httpx, requests, tenacity, BeautifulSoup |
| Frontend | React (in-browser JSX, no build step); Vite + TypeScript secondary app |
| Quality | pytest, ruff, GitHub Actions |
| Ops | Discord webhooks, cron / Windows Task Scheduler, loguru |

*mypy is configured but not enforced — do not list it as an active quality gate.*

---

## 7. Architecture facts

- Five functional areas: ingestion, feature engineering, modelling, evaluation, delivery.
- Batch pipeline; the database holds durable records, with feature parquet and model artifacts as file-based side channels.
- 14 database tables across reference, raw-signal, derived, modelling, decision and operational groups.
- Alembic migration chain builds the schema from empty (`0000`–`0008`).
- Daily pipeline sequences 13 jobs with retries on network steps and per-job audit records.
- Dual-machine deployment from a single codebase via a `NODE_ROLE` setting.
- 9 FastAPI routers.

---

## 8. Verified features

1. Multi-source ingestion (fixtures, results, bookmaker odds, weather, player data); the AFL and odds paths snapshot raw payloads before parsing, making parser bugs replayable offline.
2. Feature engineering across 11 extractors with a fold-construction leakage assertion that raises; extractor-level leakage tests cover Elo, form and bookmaker.
3. Five probabilistic models plus out-of-sample isotonic calibration and a single-source-of-truth weighted ensemble.
4. Expanding-window walk-forward backtesting with Brier, log loss, accuracy, ECE and Kelly-capped staking simulation.
5. Scheduled daily orchestration with retries on network steps and per-job audit records.
6. Credential-free reproducible demo (`make demo`) needing no API key, database or network.

---

## 9. Verified results

From `examples/backtest_2026-08-19.json` — expanding-window walk-forward, 7 test
seasons (2019–2025), 1,413 settled matches, untuned model defaults.

| Model | Brier ↓ | Log loss ↓ | Accuracy ↑ | ECE ↓ |
|---|---|---|---|---|
| **Bookmaker consensus** (benchmark) | **0.1997** | **0.5811** | **68.6%** | **0.0678** |
| Logistic regression | 0.2056 | 0.5961 | 67.7% | 0.0871 |
| Ensemble | 0.2081 | 0.6033 | 67.4% | 0.0824 |
| Elo | 0.2246 | 0.6382 | 62.1% | 0.0762 |
| XGBoost | 0.2269 | 0.6649 | 65.8% | 0.1226 |
| Poisson | 0.2558 | 0.7104 | 56.8% | 0.0926 |

**Headline: the models do not beat the market.** The benchmark wins all four
metrics in aggregate and wins Brier and log loss in every one of the seven test
seasons. The best model is ~3% worse on Brier.

That is the credible outcome for a liquid market, and the project's value is in
having measured it correctly rather than in having beaten it.

---

## 10. Engineering challenges

1. **Temporal evaluation without leakage.** Random k-fold puts future matches in
   the training set for past ones and inflates every metric invisibly. Solved
   with expanding-window folds and an assertion that raises on any training
   match kicking off after a test match, plus per-extractor time filtering and
   tests that verify a match's own result never reaches its own features.

2. **A benchmark that is actually correct.** An earlier evaluation showed the
   models comfortably beating the "bookmaker baseline" — because historical odds
   coverage was 0%, so the baseline had nothing to predict from. Backfilling real
   consensus odds moved the benchmark from 0.2430 to 0.1997 and reversed the
   conclusion. The lesson generalises: a flattering result is a reason to audit
   the baseline first.

3. **Hyperparameter selection leakage.** The tuner scripts search the same
   walk-forward folds used for reporting, so their output cannot back a
   publishable metric. Reported results use an explicit `--untuned` path with
   model constructor defaults, and running without it emits a warning.

4. **Probability–price side alignment.** A dashboard defect paired a model
   probability with the *opposite* team's market price, fabricating a +31% edge
   where the truthful figure was −17%. Fixed by an explicit invariant (each
   probability is priced only against its own side, and a missing matching price
   renders as unavailable rather than borrowing the other side) and locked with
   mutation-verified regression tests.

5. **Reproducible research artifacts.** Every published number traces to a
   committed JSON artifact and is verified against it programmatically, rather
   than being copied by hand from an old report.

---

## 11. Engineering decisions

- Database holds the durable cross-machine records; model artifacts stay local and the feature parquet moves over an authenticated sync endpoint when needed.
- Snapshot raw payloads before parsing so parser bugs are replayable offline.
- One `BaseModel` interface, so consumers never branch on model type at prediction time (registration lists still enumerate the models explicitly).
- One authoritative ensemble weight source, asserted by tests after a duplicate table caused the API to report a blend production never ran.
- Degrade rather than fail: a missing component drops out and the ensemble renormalises.
- Reject model artifacts whose stored feature count no longer matches the schema.
- Paper trading enforced structurally — no code path can place a wager.

---

## 12. Validation evidence

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | Pass |
| Tests | `pytest tests/ -q` | 344 passed, 1 skipped (345 collected) |
| Fresh-DB migration | `pytest tests/test_alembic_fresh_db.py -v` | Pass |
| Metric regeneration | `run_backtest --min-season 2017 --max-season 2025 --untuned` | Reproduces the committed artifact exactly |
| Demo | `make demo` | Pass — no `.env`, database or network |
| CI | GitHub Actions | Lint, tests, migration, demo, clean-tree gate on Python 3.11 |

---

## 13. Known limitations

- **The models do not beat the bookmaker.** Stated up front, not buried.
- Historical data only; no live or forward-tested period has been measured.
- Simulated ROI uses margin-free consensus prices (overround = 1.0) against 105–110% in real markets, so it is structurally optimistic and is not evidence of profitability.
- No bootstrap confidence intervals were computed for the canonical run, so no result carries a significance claim.
- CLV is not computable from the historical feed (one price per match).
- Player-availability features are constant (1.0, zero absences); weather measurements are entirely null with constant derived flags. Neither family contributes anything.
- Eight of nine API routers have no authentication (only `/api/sync/*` checks a shared-secret header); safe on a trusted LAN only.
- Evaluation is not bit-reproducible from a clean clone (gitignored parquet, live upstream data, unpinned ranges).
- mypy is configured but not enforced (49 errors).
- The static dashboard is a design prototype; unfed panels show placeholder values.

---

## 14. Safe portfolio claims

Each sentence is intended to survive skeptical technical review.

- "Built an end-to-end AFL match forecasting platform in Python: multi-source ingestion, leakage-safe feature engineering, five probabilistic models, calibration, walk-forward backtesting, and a FastAPI service."
- "Evaluated six models across seven AFL seasons and 1,413 matches using expanding-window walk-forward validation, scoring Brier, log loss, accuracy and calibration error."
- "Enforced temporal-leakage prevention in code — a fold-construction assertion that raises rather than warns — with extractor-level unit tests proving that a match's own result does not enter its own Elo or form features."
- "Benchmarked against a bookmaker-consensus baseline and reported the honest result: the models do not beat the market, finishing ~3% worse on Brier score."
- "Caught and corrected two evaluation-integrity defects: a degenerate bookmaker baseline caused by 0% historical odds coverage, and hyperparameter selection leakage from tuners that searched the reported folds."
- "Made every published metric traceable to a committed result artifact and verified the documentation against it programmatically."
- "Designed a daily orchestration pipeline with per-job audit records and retry handling for network steps, deployable across two machines from a single codebase via one configuration setting."
- "Shipped a credential-free reproducible demo that runs the real modelling path with no API key, database or network access."

---

## 15. Claims that must NOT be used

- ❌ "Beats the bookmaker" / "outperforms bookmaker odds" — in any framing.
- ❌ "Profitable betting system" / "positive ROI strategy" — simulated on margin-free prices, no confidence intervals, no transaction costs.
- ❌ "Production betting system" / "automated betting" — it is research software and places no bets.
- ❌ "Deployed" / "in production" — it runs locally and on a private LAN.
- ❌ "Well-calibrated model" unqualified — the benchmark is better calibrated than every model.
- ❌ "The ensemble improves accuracy, calibration or stability" — measured false on all three.
- ❌ "Statistically significant" — no confidence intervals were computed.
- ❌ "Real-time" / "live predictions" — batch, and no live period has been measured.
- ❌ Any accuracy figure quoted without its benchmark (68.6% market vs 67.7% best model).

---

## 16. Developer Hub sync

Safe fields to consume from this document:

| Field | Source |
|---|---|
| `name` | §1 |
| `description` | §2 |
| `status` | §1 — "Research" |
| `tech_stack` | §6 |
| `features` | §8 |
| `results` | §9 (always include the benchmark row) |
| `challenges` | §10 |
| `limitations` | §13 |
| `claims` | §14 only |

**Rules for any downstream surface:** never quote a model metric without the
bookmaker benchmark alongside it; never describe the project as a betting system
or as profitable; never omit that the models do not beat the market when quoting
results. If a field is not listed above, it is not approved for external use.
