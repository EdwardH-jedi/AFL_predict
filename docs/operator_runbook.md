# Operator Runbook

**Audience:** Single operator running the system during the paper trading period.  
**Purpose:** Complete daily reference. Everything you need to run the system, in order,
without consulting other documents for routine operations.

Cross-references to other docs are provided for exception paths only.

---

## Quick-reference: command summary

```bash
make pipeline          # run full daily pipeline (manual trigger)
make today-summary     # pretty-print today's JSON artifact
make freshness-check   # check data staleness
make ingest-odds       # re-fetch odds only
make ingest-afl        # re-fetch AFL fixtures only
make build-features    # rebuild feature matrix
make daily-summary     # regenerate today's JSON artifact
make serve             # start API server (localhost:8000)
make readiness         # run live-readiness report
make backtest          # run full walk-forward backtest
make train-models      # retrain all models
```

---

## Part 1 — Startup procedure

### 1a. First-time setup (once only)

```bash
# 1. Install dependencies
make install

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — required fields:
#   ODDS_API_KEY=<your key from the-odds-api.com>
#   PAPER_TRADE_ONLY=True        ← never change this during paper trading
#   DB_URL=sqlite:///./afl_predict.db

# 3. Apply all database migrations
make migrate

# 4. Verify database tables exist
python -c "from db.session import create_all_tables; create_all_tables(); print('OK')"

# 5. Run a first full pipeline to confirm end-to-end operation
make pipeline

# 6. Confirm summary artifact was written
make today-summary
```

If `make pipeline` fails at `ingest_tab_odds`: check `ODDS_API_KEY` in `.env` and confirm
your The Odds API free-tier account is active at the-odds-api.com.

### 1b. Daily startup check (every operating day, before anything else)

Before triggering the pipeline, confirm the environment is clean:

```bash
# Is the DB accessible?
python -c "from db.session import db_session; db_session().__enter__(); print('DB OK')"

# Is yesterday's artifact present? (expected to exist from the prior cron run)
ls storage/daily_summaries/ | tail -5
```

If using a server computer with cron: the pipeline may have already run. Proceed to
Part 2 to review it rather than re-running.

---

## Part 2 — Daily run procedure

### 2a. When to run

| Situation | Action |
|-----------|--------|
| Cron job ran automatically at ~08:00 AEST | Skip to Step 2c — review the artifact |
| Cron did not run or server was offline | Run `make pipeline` manually |
| Running on main computer only (no server) | Run `make pipeline` manually |

### 2b. Manual pipeline run

```bash
make pipeline
```

Expected output (abridged):

```
========== Daily pipeline starting [YYYY-MM-DD] triggered_by=manual ==========
[check_data_freshness]  starting ...
[ingest_afl]            starting ...
[ingest_tab_odds]       starting ...
[build_features]        starting ...
[generate_recommendations] starting ...
[settle_results]        starting ...
[generate_daily_summary] starting ...
========== Daily pipeline SUCCESS in 42.3s ==========
```

**If the pipeline exits with status `failed`:** go to Part 4 (exception handling).  
**If the pipeline exits with status `partial_failure`:** one soft job failed — proceed to
review but note which job failed before accepting recommendations.

### 2c. Read today's artifact

```bash
make today-summary
```

Check these fields in order:

| Field | Acceptable | Action if not acceptable |
|-------|-----------|--------------------------|
| `pipeline.status` | `success` or `partial_failure` | See Part 4 |
| `freshness.odds_stale` | `false` | See Part 5 (stale data) |
| `freshness.afl_stale` | `false` | Run `make ingest-afl` then `make pipeline` |
| `freshness.upcoming_without_odds` | `0` | Run `make ingest-odds` |
| `no_bet_day.is_no_bet_day` | either | See Part 6 (no-bet handling) |
| `bankroll.drawdown` | `< 0.25` | If >= 0.25: pause; see drawdown protocol below |

### 2d. Drawdown protocol

If `bankroll.drawdown >= 0.25`:
1. Do not record any recommendations from today.
2. Do not run `make pipeline` again until the cause is reviewed.
3. Open `storage/paper_trading_log.md` and add a PAUSE entry.
4. Review the last 10 bet outcomes: `curl http://localhost:8000/dashboard/recommendations`
5. Determine whether the drawdown is accumulated variance or a systematic error.
6. Resume only after completing a mini-review (see Part 7b).

---

## Part 3 — Review procedure

### 3a. Pre-acceptance recommendation review (match days only)

Before recording any recommendation as a paper trade, complete all four checks:

**Check 1 — Freshness**  
`freshness.odds_stale` must be `false`.  
If stale: **do not count recommendations today.** Log as stale-data day (see Part 5).

**Check 2 — Match plausibility**  
For each recommendation in the artifact:
- Does the match exist? Cross-check against the current AFL round.
- Is `match_date` in the future?
- Are both team names recognisable? (Normalisation failures produce garbled names.)

**Check 3 — Field sanity**  
For each recommendation:

| Field | Must be |
|-------|---------|
| `side` | `home` or `away` |
| `odds` | > 1.01 |
| `stake_fraction` | > 0 and <= 0.05 |
| `paper_trade` | `true` — **stop and investigate if false** |
| `status` | `pending` |

**Check 4 — Pipeline source**  
Confirm `generate_recommendations` completed in `pipeline.jobs`.  
If `records_processed = 0` on a known match day: the model found no edge today — valid no-bet.

### 3b. Recording the day

Open `storage/paper_trading_log.md` and add an entry. See
`docs/paper_trading_operation_plan.md` section 4 for the exact entry format.

Minimum entry every day — no exceptions. A no-bet day without an entry is an unaccountable gap.

### 3c. Via API (if server is running)

```bash
# Start server if not already running
make serve

# Open any of these
curl http://localhost:8000/dashboard/summary        | python -m json.tool
curl http://localhost:8000/dashboard/recommendations | python -m json.tool
curl http://localhost:8000/dashboard/bankroll        | python -m json.tool
curl http://localhost:8000/dashboard/freshness       | python -m json.tool
curl http://localhost:8000/dashboard/pipeline        | python -m json.tool
```

Or open `http://localhost:8000/docs` in a browser for the full Swagger UI.

---

## Part 4 — Exception handling

### Pipeline status: `failed` (hard-dep failure)

1. Identify which job failed:
   ```bash
   curl http://localhost:8000/dashboard/pipeline | python -m json.tool
   # Or without API:
   python -c "
   from db.session import db_session
   from db.models.pipeline_runs import PipelineRun
   with db_session() as db:
       rows = db.query(PipelineRun).order_by(PipelineRun.id.desc()).limit(10).all()
       for r in rows: print(r.job_name, r.status, r.error_message)
   "
   ```
2. Follow the job-specific recovery steps in `docs/ops_failed_pipeline.md`.
3. Re-run the pipeline after fixing the root cause: `make pipeline`
4. **Do not count recommendations from a day where the pipeline ultimately failed.**
5. Log in `storage/paper_trading_log.md` as an `[INTEGRITY FAILURE]` entry.

### Pipeline status: `partial_failure` (soft-job failure)

The hard-dep jobs succeeded. Data is fresh. Whether today's recommendations are valid
depends on which soft job failed:

| Failed job | Recommendations valid? | Action |
|-----------|----------------------|--------|
| `generate_recommendations` | No recs generated | Check model runs; retry job; mark as no-bet day if unresolvable |
| `settle_results` | Yes (affects prior days only) | Retry: `python -m orchestration.jobs.settle_results` |
| `generate_daily_summary` | Yes | Retry: `make daily-summary` |

### DB migration error

If you see a SQLAlchemy column-not-found or table-not-found error:
```bash
make migrate    # applies any pending alembic migrations
make pipeline   # retry
```

### Odds API quota exhausted

The free tier allows 500 requests/month. If `ingest_tab_odds` fails with a 429 or quota
error:
1. Log in at the-odds-api.com to confirm quota state.
2. If exhausted: no recommendations are possible until quota resets (monthly).
3. Log every affected day as a stale-data day.
4. Consider running `make ingest-odds` less frequently to preserve quota for match days.

### Unknown team alias in odds data

If recommendations reference garbled team names, check the team normaliser:
```bash
python -c "
from collectors.team_normalizer import TeamNormalizer
n = TeamNormalizer()
print(n.get_unknown_aliases())
"
```
Add any unknown aliases to `collectors/team_normalizer.py` and re-run `make ingest-odds`
and `make build-features`.

---

## Part 5 — Stale-data handling

**Detection:** `freshness.odds_stale: true` or `freshness.afl_stale: true` in the artifact.

### Stale odds

```bash
# Attempt recovery
make ingest-odds

# Verify
make freshness-check
```

If recovery succeeds before the first match kick-off of the day: re-run `make pipeline`.
Recommendations generated after successful recovery are valid.

If recovery fails (API error, quota exhausted):
1. Do not generate or count recommendations today.
2. Log as `[STALE-DATA DAY]` in `storage/paper_trading_log.md`.
3. See `docs/ops_stale_data.md` for full recovery steps.

### Stale AFL fixtures

```bash
make ingest-afl
make freshness-check
```

AFL data goes stale less often (48h threshold). If stale on a match day, prioritise
fixing before odds ingestion.

### Do not:
- Raise `ODDS_FRESHNESS_HOURS` in `.env` to avoid seeing the warning — that corrupts the record.
- Count recommendations generated from stale odds in paper trading performance.

---

## Part 6 — No-bet handling

A no-bet day occurs when `no_bet_day.is_no_bet_day: true` in the artifact.

### Valid reasons for a no-bet day

| Reason | What it means |
|--------|--------------|
| No upcoming matches | AFL bye round, off-season, or round not yet scheduled |
| Edge below threshold | Model found no match where `model_prob - bm_implied_prob >= MIN_EDGE_THRESHOLD` |
| No recommendations generated | `generate_recommendations` produced 0 records (no error — just no edge) |
| Data was stale (handled in Part 5) | Stale-data days that produced no valid recommendations |

### What to do on a no-bet day

1. Confirm the reason from the artifact (`no_bet_day.reason`).
2. Log in `storage/paper_trading_log.md` as a `[NO-BET DAY]` entry.
3. Do not attempt to force a recommendation by lowering the threshold.
4. Move on. No-bet days are expected and healthy.

### Tracking no-bet frequency

Check cumulative no-bet rate in the weekly review (see Part 7a). If >70% of AFL match
days over a 2-week window are no-bet days, flag it in the weekly review notes for
threshold review at the 30-day mark.

---

## Part 7 — End-of-day and end-of-week review

### 7a. End-of-day (optional, ~match kick-off time, match days only)

After the day's matches have kicked off, confirm:

```bash
# Paper bets for today are in pending state (not yet settled — normal)
curl http://localhost:8000/dashboard/recommendations | python -m json.tool | grep '"status"'

# Bankroll hasn't changed unexpectedly (settle_results only runs during pipeline)
curl http://localhost:8000/dashboard/bankroll | python -m json.tool
```

No action required unless drawdown > 25% (see Part 2d).

### 7b. End-of-week review (Monday or first day of each new AFL round)

The weekly review is a structured 30–45 minute process. Follow
`docs/weekly_review_framework.md` in full.

**Quick version for a clean week:**

```bash
# 1. Confirm a summary artifact exists for every day of the week
ls storage/daily_summaries/ | tail -7

# 2. Pull pipeline health for the week
curl "http://localhost:8000/dashboard/pipeline?days=7" | python -m json.tool

# 3. Pull bankroll trend
curl "http://localhost:8000/dashboard/bankroll?days=7" | python -m json.tool

# 4. Read paper trading log entries for the week
tail -100 storage/paper_trading_log.md

# 5. Run live-readiness report (weekly habit)
make readiness
```

Fill in the weekly record table in `docs/weekly_review_framework.md`.

After 4 weeks, run the full 30-day review: see `docs/ops_30day_review.md`.

---

## Part 8 — Decision: when to retrain models

Retrain models only on a deliberate schedule, not reactively:

| Trigger | Action |
|---------|--------|
| New AFL season data available | `make ingest-afl && make build-features && make train-models` |
| 30-day review shows Brier score degraded | `make train-models && make backtest` |
| Model loading TODO is resolved | Retrain to confirm new dispatch works |
| Never: after a bad week | Do not retrain reactively |

After retraining, always run the backtest to confirm no regression:
```bash
make backtest
```

---

## Part 9 — Pre-round checklist (before each new AFL round)

Run this before Friday/Saturday of each new round:

```bash
# 1. Confirm AFL fixtures are loaded for the upcoming round
make ingest-afl

# 2. Confirm odds are present for all upcoming matches
make ingest-odds
make freshness-check     # upcoming_without_odds should be 0

# 3. Run the pipeline (will generate recommendations if edge is found)
make pipeline

# 4. Review today's artifact
make today-summary
```

If `upcoming_without_odds > 0` after ingest: odds may not yet be published by the bookmaker.
Retry on the morning of the first match day of the round.

---

## Part 10 — Reference: document map

| Situation | Document |
|-----------|----------|
| Pipeline job failed — what to do | `docs/ops_failed_pipeline.md` |
| Stale data — full recovery steps | `docs/ops_stale_data.md` |
| Daily paper trading checklist | `docs/paper_trading_operation_plan.md` |
| Weekly review — all 8 dimensions | `docs/weekly_review_framework.md` |
| 30-day review template | `docs/ops_30day_review.md` |
| Live-readiness checklist | `docs/ops_live_readiness.md` |
| Multi-machine setup | `ops/machine_workflows.md` |
| Parameter change process | `docs/recommendation_quality_iteration.md` |
| Feature catalogue | `docs/features.md` |
| Backtest methodology | `docs/backtesting.md` |

---

## Appendix: environment variables reference

Key settings in `.env` that affect daily operations:

| Variable | Default | Notes |
|----------|---------|-------|
| `PAPER_TRADE_ONLY` | `True` | Never change during paper trading |
| `MIN_EDGE_THRESHOLD` | `0.03` | See `recommendation_quality_iteration.md` before changing |
| `MAX_KELLY_FRACTION` | `0.05` | Hard risk cap — do not raise |
| `ODDS_FRESHNESS_HOURS` | `26` | See stale data doc before changing |
| `AFL_FRESHNESS_HOURS` | `48` | |
| `ODDS_API_KEY` | (required) | Get from the-odds-api.com |
| `DB_URL` | `sqlite:///./afl_predict.db` | Change to PostgreSQL URL if using server |

Changing any of these requires a note in `storage/paper_trading_log.md`.
