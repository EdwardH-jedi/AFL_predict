# AFL Predict — Claude Code Skills

Paste any prompt below directly into the Claude Code chat to invoke that skill.
Skills are grouped by workflow. Arguments in `<angle brackets>` are optional overrides.

---

## Daily Operations

### `/picks`
```
Show me today's pending AFL recommendations.
Query the DB for all Recommendation rows with status='pending'. For each, join to Prediction, Match, and Team to show:
- Pick team vs opponent
- Match time in AEST
- Venue + is_neutral_venue flag
- Model win probability for the pick side
- Bookmaker implied probability (bm_home_implied_prob or bm_away_implied_prob)
- Edge (model prob - bm implied)
- Recommended odds and Kelly fraction
- Model run ID and brier score
Format as a clean table. Flag any picks where is_neutral_venue=True with "(NEUTRAL)".
```

### `/discord`
```
Re-send today's AFL picks to Discord.
Run: python -m orchestration.jobs.notify_bets
Show the log output. If it fails, show the error and diagnose the cause (Discord webhook URL in .env, httpx connectivity, message length >2000 chars).
```

### `/daily-pipeline`
```
Run the full AFL daily pipeline manually and summarise the result.
Run: python -m orchestration.daily_pipeline --triggered-by manual
After it completes, print the job-by-job status table from the log.
Highlight any FAILED or SKIPPED jobs and their error messages.
```

### `/settle`
```
Settle any completed AFL matches against pending recommendations.
Run: python -m orchestration.jobs.settle_results
Then query BetOutcome and show a summary:
- Number of bets settled today
- Win/loss breakdown
- Profit/loss in Kelly units
If no bets settle, explain why (pending results, no completed matches).
```

### `/summary`
```
Show today's daily summary artifact.
Run: python -m orchestration.jobs.generate_daily_summary
Then pretty-print storage/daily_summaries/<today>.json.
Highlight: pending picks count, freshness warnings, bankroll state, last pipeline status.
```

---

## Data Ingestion

### `/ingest`
```
Ingest the latest AFL fixtures, results, and bookmaker odds.
Run both in sequence:
  python -m orchestration.jobs.ingest_afl
  python -m orchestration.jobs.ingest_tab_odds
Show row counts inserted/updated for matches and odds_snapshots.
Flag any HTTP errors or missing odds for upcoming matches.
```

### `/ingest-round <season> <round>`
```
Ingest AFL data for a specific season and round (use for backfilling).
Run: python -m orchestration.jobs.ingest_afl --season <season> --round <round>
Show which match records were created vs updated, and whether results were recorded.
Default to current season/round if no args given.
```

### `/freshness`
```
Check whether fixture and odds data is fresh enough to trade on.
Run: python -m orchestration.jobs.check_data_freshness
Report:
- Age of newest odds snapshot vs settings.odds_freshness_hours threshold
- Age of newest AFL fixture record vs settings.afl_freshness_hours threshold
- Any upcoming matches with no odds snapshot
- Verdict: FRESH / STALE / MISSING
```

---

## Feature Engineering

### `/build-features`
```
Rebuild the full pre-match feature matrix parquet from the database.
Run: python -m orchestration.jobs.build_features
After it completes, show:
- Path and filename of the new parquet
- Total rows, settled vs upcoming split
- Column list (all 40+ features)
- Value counts for is_neutral_venue
- Any columns with >10% NaN in the settled set
```

### `/feature-audit`
```
Audit the latest features parquet for data quality issues.
Load storage/raw_snapshots/features/features_*.parquet (newest by mtime).
Report:
- Total rows, settled vs upcoming
- For each column in FEATURE_COLS (from models/logistic_baseline.py): % NaN, min, max, mean
- Columns in the parquet but NOT in FEATURE_COLS (unused features)
- Columns in FEATURE_COLS but NOT in the parquet (missing features — will be dropped at fit)
- is_neutral_venue distribution: 0 vs 1 counts for settled and upcoming rows
```

---

## Model Training & Evaluation

### `/train`
```
Retrain all baseline models on the latest temporal split and compare metrics.
Run: python -m orchestration.jobs.train_models
After training, query ModelRun for the latest completed runs for each model and display a comparison table:
  Model              | Brier Score | Log Loss | Accuracy | Features | Trained At
  bookmaker_baseline | ...         | ...      | ...      |          |
  elo_baseline       | ...         | ...      | ...      |          |
  logistic_baseline  | ...         | ...      | ...      | n=13     |
Highlight the best (lowest) brier score. Note which model generate_recommendations will use.
```

### `/backtest`
```
Run the full walk-forward backtest across all seasons and display results.
Run: python -m orchestration.jobs.run_backtest
Then show the per-fold and aggregate metric table for each model:
- Brier score, log loss, accuracy per fold
- Decision metrics: n_bets, hit_rate, avg_edge, ROI
- Calibration ECE
Highlight the best-performing model and any folds with suspiciously high/low metrics.
```

### `/model-status`
```
Show all completed model runs ranked by Brier score.
Query ModelRun where status='completed', order by brier_score ASC.
Display a table:
  rank | model_name        | brier  | logloss | accuracy | run_id | completed_at | artifact_exists
Show which run_id would be selected by generate_recommendations (lowest brier, artifact on disk).
Check that the .pkl file at artifact_path actually exists and load its fit_features list.
```

### `/model-compare`
```
Compare the last training run for each model type head-to-head.
For each model (bookmaker_baseline, elo_baseline, logistic_baseline), take the most recent completed ModelRun.
Show:
- Brier score vs 0.25 baseline (coin-flip) and bookmaker benchmark
- How much each model beats/loses to the bookmaker on Brier score
- The skill score: (brier_model - brier_baseline) / (0 - brier_baseline) * 100%
Interpret the results in plain English.
```

---

## Neutral Venue & ELO Audit

### `/neutral-check`
```
Audit is_neutral_venue flags for all upcoming matches.
Query all matches where result IS NULL (upcoming). For each:
- Show venue, home_team, away_team, is_neutral_venue
- Cross-check against collectors/venue_rules.py TEAM_HOME_VENUES to verify correctness
Highlight any mismatches: games flagged neutral that shouldn't be, or vice versa.
Also show the ELO expected-win probabilities with and without home advantage (+50 points)
for any neutral venue game, to quantify the impact of the flag.
```

### `/elo-snapshot`
```
Show current ELO ratings for all 18 teams.
Re-run EloExtractor over all settled matches in chronological order.
Display a table sorted by current rating:
  Team              | ELO Rating | Change this season | Last 5 results
Also show: average ELO, spread (max - min), number of teams above/below 1500.
```

---

## System Health

### `/readiness`
```
Run the live-readiness evaluation and show the full report.
Run: python -m evaluation.live_readiness
Display each of the 7 checks with status (PASS / WARN / FAIL):
  1. sample_size    — enough settled paper bets
  2. drawdown       — max bankroll drawdown
  3. calibration    — ECE on recent predictions
  4. ingestion_health — hard-dep job failures last 7 days
  5. stale_data     — recurring stale-data warnings
  6. roi            — paper-trade ROI
  7. critical_todos — unresolved critical items
Show overall verdict: ready / marginal / not_ready.
```

### `/db-status`
```
Show a health snapshot of the SQLite database.
Query row counts for all key tables:
  Table              | Rows  | Latest record
  teams              | ...   | ...
  matches            | ...   | ...
  odds_snapshots     | ...   | ...
  predictions        | ...   | ...
  recommendations    | ...   | ...
  bet_outcomes       | ...   | ...
  model_runs         | ...   | ...
  pipeline_runs      | ...   | ...
Also show: DB file size, count of pending vs settled vs void recommendations,
count of completed vs upcoming matches, and any matches missing odds for the next 7 days.
```

### `/pipeline-history`
```
Show the last 7 daily pipeline runs with job-level status.
Query DailyPipelineRun and PipelineRun for the last 7 days.
For each day, show which jobs passed, failed, or were skipped and any error messages.
Highlight recurring failures.
```

### `/clv`
```
Compute and display the Closing Line Value (CLV) report for all settled bets.
Run the clv_summary() from evaluation/clv_tracker.py:
  python -c "from db.session import SessionLocal; from evaluation.clv_tracker import batch_clv, clv_summary; db=SessionLocal(); r=batch_clv(db); print(clv_summary(r)); db.close()"
Interpret the result: positive CLV means the model is consistently beating the closing line,
a strong signal of long-term edge. Explain what the confidence interval means.
```

---

## Database & Schema

### `/migrate`
```
Run pending Alembic database migrations safely.
First run: alembic history --verbose  to show current head vs applied revisions.
Then run: alembic upgrade head
Show which migrations were applied. If a migration fails, show the full error
and check whether the column/table already exists (SQLite doesn't support ALTER TABLE DROP COLUMN easily).
```

### `/db-query <natural language question>`
```
Answer a data question about the AFL predict database using SQL.
Translate the question into a SQLAlchemy query or raw SQL against afl_predict.db.
Show the query and the result. Example questions:
- "Which team has the highest ELO heading into Round 5?"
- "How many picks have been sent since the start of the season?"
- "What is the ROI on logistic_baseline recommendations so far?"
- "Show all matches where we picked the home team at neutral venue"
```

---

## Odds & Market Analysis

### `/odds-audit`
```
Audit current bookmaker odds against model probabilities for upcoming matches.
Query all upcoming matches with odds and pending predictions. For each:
- Show model home_win_prob vs bm_home_implied_prob
- Compute overround: 1/home_odds + 1/away_odds
- Flag if overround > 1.08 (excessive vig erodes edge)
- Rank by edge descending
Identify any matches where edge sign flips after removing overround.
```

### `/market-move`
```
Check for significant odds movement since the last ingestion.
Query OddsSnapshot for upcoming matches and compare the two most recent snapshots per match.
Flag any match where home or away odds moved by more than 0.2 (absolute).
Large moves can indicate sharp money, team news, or data quality issues.
Show: match, old odds → new odds, direction (shortening/drifting), time of move.
```

---

## Diagnostics

### `/debug-pipeline`
```
Diagnose why the last pipeline run failed or produced 0 recommendations.
Check in order:
1. Last DailyPipelineRun status and any failed jobs
2. Latest PipelineRun records for ingest_afl, ingest_tab_odds, build_features, generate_recommendations
3. Whether the features parquet exists and has upcoming rows
4. Whether any ModelRun completed successfully with an artifact on disk
5. Whether upcoming matches have bm_home_implied_prob populated
6. Whether min_edge_threshold in settings filters out all picks
Report the first step that fails and the likely fix.
```

### `/debug-discord`
```
Diagnose why Discord picks were not sent.
Check in order:
1. DISCORD_WEBHOOK_URL in .env — is it set and non-empty?
2. Last PipelineRun record for notify_bets — status and error_message
3. Pending recommendations count (0 picks = nothing to send)
4. Last 50 lines of logs/ for Discord-related errors
5. Test the webhook with a minimal message using httpx
Report exactly which step fails.
```

### `/retrain-and-repick`
```
Full reset of model and recommendations for today.
Run in sequence:
  1. python -m orchestration.jobs.train_models       # retrain on latest features
  2. python -m orchestration.jobs.generate_recommendations  # void stale + create fresh picks
  3. python -m orchestration.jobs.notify_bets        # send to Discord
After each step, confirm it completed successfully before continuing.
Show the final pick list with probabilities and edges.
```
