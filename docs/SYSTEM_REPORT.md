# AFL_predict — System Report

**Scope:** Models · Betting strategy · Data · Backend tech stack
**Nature of system:** Paper-trading AFL value-betting *research* platform. Analytics and alerts only — **no automatic bet placement anywhere in the codebase.**

---

## 1. Prediction Models

Every model inherits `BaseModel` (`models/base_model.py`), an ABC whose contract is a DataFrame of `[match_id, home_win_prob, away_win_prob]` summing to 1.0. **All models predict a binary home-win probability** (head-to-head), not margin or score directly.

| Model | File | Algorithm / library | Key config |
|---|---|---|---|
| **Bookmaker baseline** | `bookmaker_baseline.py` | None — passthrough of de-vigged bookmaker implied probs | Stateless; `fit()` is a no-op. Serves as the "hardest to beat" ceiling |
| **Elo baseline** | `elo_baseline.py` | Custom Elo, standard logistic expected-score | `k=30`, `home_adv=60`, `season_regression=0.3`, `init=1500`; requires chronological rows |
| **Logistic** | `logistic_baseline.py` | sklearn `Pipeline`: median `SimpleImputer` → `StandardScaler` → `LogisticRegression` | `C=1.0`, `max_iter=1000`, `random_state=42`; 29-col feature set |
| **XGBoost** | `xgboost_model.py` | `xgboost.XGBClassifier` (CUDA auto-detect on RTX 5080) | `n_estimators=300`, `max_depth=4`, `lr=0.05`, `subsample=0.8`, `colsample=0.8`, `early_stopping=20`, `eval_metric=logloss` |
| **Poisson** | `poisson_model.py` | Dual-mode: two `statsmodels` GLM Poisson (home & away scoring, convolved via `scipy.stats.poisson`) when ≥50 scored rows; else isotonic fallback on bookmaker prob | Win prob clipped to [0.01, 0.99] |

**Calibration** — `calibrated_model.py` wraps a base model with **isotonic regression** (`sklearn.isotonic.IsotonicRegression`, *not* Platt/sigmoid). Fitted on a held-out calibration set (skipped if <30 samples); logs ECE before/after. In production only the **logistic** and **XGBoost** models are wrapped in a calibrator.

**Ensemble** — `ensemble.py` produces a normalized **weighted average** of component probabilities.
- An `optimize_weights()` method exists (minimizes Brier score via `scipy.optimize.minimize`, Nelder-Mead) **but is not called in the production path.**
- Production weights are **static config values**, single-sourced from
  `config/settings.py` (`ensemble_weight_*`: logistic 0.30 / xgboost 0.35 /
  poisson 0.20 / elo 0.15) and consumed by both
  `orchestration/jobs/generate_recommendations.py` and the dashboard API.

**Hyperparameter tuning** — grid search with expanding-window walk-forward validation, ranked by fold-size-weighted mean Brier score (**no Optuna/Bayesian search**):
- `backtesting/xgb_tuner.py` — 144-combo grid (depth × lr × n_estimators × subsample) → `xgb_best_params.json`
- `backtesting/elo_tuner.py` — 64-combo grid (K × home_adv × regression) → `elo_best_params.json`
- Both JSONs are loaded by `train_models.py` to override defaults; absent → defaults.

**Training** (`train_models.py`) — temporal split (train = seasons 1..N−1, val = season N), calibration on the penultimate season; calibrated models are deliberately **not** refit on full train afterward (prevents desyncing the isotonic map — ECE had ballooned to 0.31). Logs XGBoost gain-based feature importances.

---

## 2. Betting / Staking Strategy

**Value / edge** — `edge = model_prob − bookmaker_implied_prob` (a raw probability difference). Implied probs are **de-vigged** by proportional normalization (`raw = 1/odds`, divide by total book overround), done in `collectors/transformers/odds_transformer.py`.

**Staking — full Kelly, hard-capped (not fractional Kelly).**
- `f = (b·p − (1−p)) / b`, where `b = odds − 1`, `p = model_prob`, clamped to `[0, max_kelly_fraction]`.
- Design choice is explicit: *no* fractional multiplier — instead the cap is set conservatively low.

**Bankroll rules**
- Min edge to bet: `min_edge_threshold = 0.03` (3%)
- Max stake: `max_kelly_fraction = 0.05` (5% hard cap)
- One bet per match max — the higher-edge side (ties favor home)
- Live bankroll base: `1000.0` units

**Abstention** — no bet when: both sides' edge < 3%; odds missing for the chosen side; Kelly ≤ 0 (negative edge); or implied-prob columns absent.

**Confidence banding — two independent schemes:**
- *Edge-based* (React dashboard, `frontend/src/lib/confidence.ts`): ≥0.08 strong 🔥 / ≥0.05 moderate / ≥0.03 marginal / else none
- *Probability-based* (static quant dashboard, `generate_predictions_json.py`): distance from coin-flip → ≥0.65 HIGH / ≥0.55 MED / else LOW

**CLV (Closing Line Value)** — `evaluation/clv_tracker.py`: `clv = (1/closing_odds) − (1/bet_odds)`; positive = beat the close. Closing odds = latest `OddsSnapshot` before match time. Reports `beat_closing_line` %, avg/median CLV. *(Uses raw single-side reciprocals, not de-vigged.)* Cited as the primary long-term profitability signal.

**Live-readiness gate** — `evaluation/live_readiness.py`, 7 checks (pass/warn/fail; any fail → `not_ready`). Decision-support only; a human makes the final go/no-go call:

| Check | Pass criterion |
|---|---|
| Sample size | ≥ 100 settled paper bets |
| Drawdown | max bankroll DD < 25% |
| Calibration | Brier (ECE proxy) < 0.06 on last 200 preds |
| Ingestion health | 0 hard-dep job failures in 7d |
| Stale data | 0 failed/partial daily runs in 7d |
| ROI | paper ROI/unit ≥ −0.05 |
| Critical TODOs | none — **fails while `tab_bookmaker_confirmed=False`** |

**Paper-trading only — confirmed and enforced:** global `paper_trade_only=True`; every recommendation hardcoded `paper_trade=True`; the risk-manager audit raises a **critical** violation if any rec is `paper_trade=False`. No real-money execution path exists.

---

## 3. Data Sources & Features

### Raw data ingested

| Domain | Source | Access |
|---|---|---|
| AFL fixtures / results / teams | **Squiggle API** (`api.squiggle.com.au`) | Free, no key, descriptive User-Agent |
| Live H2H odds | **The Odds API** (`aussierules_afl`, AU region, decimal) | Free tier 500 req/mo; TAB/Sportsbet/Unibet/Betfair AU |
| Historical odds (consensus) | Squiggle **tips** API (Punters.com.au consensus) | Same Squiggle endpoint |
| Historical odds (scrape) | **Footywire** HTML scrape (BeautifulSoup) | Public |
| Weather | **Open-Meteo** forecast + archive APIs (per-venue GPS) | Free, no key |
| Player stats / availability | **AFL Tables** CSV (`afltables.com`, back to 1897) | Public |
| Bet-message read-back | **Discord REST API v10** (bot token) | Not a predictive source |

> "TAB odds" is not a dedicated endpoint — it arrives via The Odds API's AU feed if the subscription tier includes it (flagged unconfirmed via `tab_bookmaker_confirmed`). Every collector snapshots the raw payload to `storage/raw_snapshots/<source>/` before parsing.

### Feature families (`features/extractors/`, 11 extractors)

All subclass `BaseExtractor`, return `{match_id: {feature: value}}`, and enforce a **pre-match leakage policy** (only prior/complete matches, `snapshot_time < match_time`):

- **Elo** — pre-match ratings, `elo_diff` (chronological replay; K=32, +50 home adv zeroed on neutral venues, 25% season regression)
- **Form** — win rates L3/L5/L10, avg pts for/against L10, momentum (L3−L10)
- **Rest days** — calendar days since each team's prior match
- **Venue** + **Venue performance** — neutral flag; per-(team,venue) win rate, venue home advantage (min 5 games)
- **Head-to-head** — directional L5 win rate, avg margin, games played (min 2 meetings)
- **Travel** — interstate flag, travel km, km diff (team state vs venue state)
- **Weather** — temp, wind, precip, rain/wind/heat flags, composite scoring index
- **Player availability** — availability index, key players absent, diff
- **Bookmaker** — odds, implied probs, overround (latest pre-match snapshot)
- **Odds movement** — opening vs latest drift, line-move classification

### Assembly & persistence

- `features/feature_builder.py` `DatasetBuilder.build(season)` runs all extractors chronologically, attaches the `home_win` target + scores, and runs leakage / range / null-rate validators.
- **Parquet** snapshot (`storage/raw_snapshots/features/…parquet`) — full feature set, used for model training.
- **DB table `match_features`** — a **subset** only (Elo, L10 form, bookmaker odds, rest, venue, target). The richer H2H / travel / weather / availability / odds-movement features live only in parquet.

---

## 4. Backend Tech Stack

**Language / runtime:** Python 3.11, `.venv`. Dual-machine GPU deployment — collector node (AMD RX 6600, ingestion) and predictor node (NVIDIA RTX 5080, modelling); XGBoost auto-detects CUDA, falls back to CPU.

**Web / API**
- **FastAPI** (`>=0.111`) app factory `api/main.py:create_app()`, served by **uvicorn[standard]**. CORS restricted to GET/POST; `/static` mount for dashboards.
- Routers: `/health`, `/fixtures`, `/predictions`, `/recommendations`, `/dashboard/*` (legacy HTML API), `/api/dashboard/*` (typed React UI, Pydantic response models), `/api/sync`, `/api/tab` (manual TAB bet tracking), `/discord/*`.

**Config** — **pydantic-settings** + pydantic v2 + python-dotenv; `.env`-driven `Settings` singleton (`@lru_cache`). Controls DB URL, data-source keys, pipeline thresholds, ensemble weights, `node_role`, Discord.

**Database** — **SQLAlchemy 2.x** (typed `Mapped`/`mapped_column`, `DeclarativeBase`); **Alembic** migrations (0001–0008). Default **SQLite** (`afl_predict.db`); overridable to **PostgreSQL** via `psycopg2-binary`. ~14 ORM models (matches, odds_snapshots, predictions, recommendations, bet_outcomes, bankroll_logs, match_features, weather_snapshots, player_lineups/stats, pipeline runs, teams).

**HTTP / scraping** — **httpx** (async), **requests** (sync fallback), **tenacity** (retry), **beautifulsoup4** + **lxml** (scraping).

**Orchestration** — `orchestration/daily_pipeline.py` (`python -m orchestration.daily_pipeline`). Job registry: freshness → ingest_afl → ingest_tab_odds → build_features → generate_recommendations → notify_bets → settle_results → daily_summary → 5 role audits (data_steward, feature_engineer, model_engineer, risk_manager, quant_reviewer). `pipeline_state.py` state machine with retries; hard-dep failures skip downstream hard-dep jobs; `NODE_ROLE` filters which jobs run. Runs persisted to DB.

**Scheduling** — **Windows Task Scheduler** (`ops/windows_tasks/`, primary on this Windows box): weather 07:00, pipeline 08:00, weekly train Sun 03:00. **Linux cron** alternative in `ops/crontab_server.txt`.

**Notifications** — Discord: outbound webhook (`notify_bets.py`, httpx + retry, gated by `discord_enabled`) and inbound read-back (`discord_reader.py`, bot token, regex-parses posted picks). Never places bets.

**Frontend serving** — legacy `static/dashboard.html` + `static/quant-dashboard/` (CDN React-in-JSX), plus a `frontend/` **Vite + React 18 + TypeScript + Tailwind + recharts + SWR** scaffold (dev-proxies `/api` and `/dashboard` to :8000). Standalone preview via `serve.py` (stdlib http.server, :8080).

**Quality** — **pytest** + pytest-asyncio (`asyncio_mode=auto`), **ruff** (line 100, py311, `E,F,I,UP`), **mypy** (py311, non-strict). ML/analytics libs: scikit-learn, statsmodels, scipy, shap, joblib, pandas, numpy, pyarrow, matplotlib.

---

## Notable observations

- **`optimize_weights()` is dead in production** — defined (Nelder-Mead Brier minimization) but never invoked; weights are static.
- **Feature loss between parquet and DB** — `match_features` persists only a subset; models train from parquet, so the DB table under-represents the true feature vector.

Resolved since this report was first written:

- ~~Ensemble weight discrepancy~~ — weights are now single-sourced from `config/settings.py`; the recommendations job and dashboard read the same values.
- ~~Readiness import mismatch~~ — `risk_manager.py` now imports `evaluate as evaluate_readiness`.
- ~~Stray repo-root artifacts~~ — the accidental pip-redirect files (`=0.14`, `=0.44`, `=2.0`) have been removed from the repository.
