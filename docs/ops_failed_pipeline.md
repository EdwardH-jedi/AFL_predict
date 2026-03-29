# Failed Pipeline Runbook

What to do when the daily pipeline fails.

---

## 1. Identify the failure

Check which job failed and what the error was:

```bash
# Via API
curl http://localhost:8000/dashboard/pipeline?days=1

# Via DB (SQLite example)
sqlite3 afl_predict.db \
  "SELECT job_name, status, error_message, retry_count
   FROM pipeline_runs
   WHERE daily_run_id = (SELECT MAX(id) FROM daily_pipeline_runs)
   ORDER BY id;"
```

Look for `status = 'failed'` rows.

---

## 2. Hard-dep failure (ingest_afl, ingest_tab_odds, build_features)

These failures leave the pipeline in **`failed`** state and skip downstream jobs.

### ingest_afl failed

```
Likely causes:
  - Squiggle API down or rate-limited
  - Network unavailable on server
  - Season/round parameter mismatch

Actions:
  1. Check https://api.squiggle.com.au/?q=games (manual browser test)
  2. Wait 30–60 minutes and retry: make ingest-afl
  3. If API is down for >4h, mark as known outage and skip — recommendations
     cannot be generated until AFL data is fresh
```

### ingest_tab_odds failed

```
Likely causes:
  - The Odds API key exhausted (500 req/month on free tier)
  - TAB bookmaker not returned in API response
  - Network error

Actions:
  1. Check API quota: log into the-odds-api.com dashboard
  2. If quota exhausted: skip odds ingestion for today; no recommendations possible
     until quota resets (monthly)
  3. Retry: make ingest-odds
```

### build_features failed

```
Likely causes:
  - DB schema mismatch (run alembic upgrade head)
  - Match table empty (ingest_afl must succeed first)
  - Feature extractor code error

Actions:
  1. Check DB: sqlite3 afl_predict.db "SELECT COUNT(*) FROM matches;"
  2. Run migration if needed: make migrate
  3. Retry: make build-features
```

---

## 3. Soft-job failure (generate_recommendations, settle_results, generate_daily_summary)

These leave the pipeline in **`partial_failure`** state.
Hard-dep jobs completed successfully.

### generate_recommendations failed

```
Likely causes:
  - No trained model available (run make train-models first)
  - Feature matrix is empty
  - DB write error

Actions:
  1. Check model runs: SELECT * FROM model_runs ORDER BY id DESC LIMIT 3;
  2. If no models: make train-models
  3. Retry: python -m orchestration.jobs.generate_recommendations
```

### settle_results failed

```
Actions:
  1. Check pending recommendations: SELECT * FROM recommendations WHERE status='pending';
  2. Check match results are in: SELECT result FROM matches WHERE result IS NOT NULL LIMIT 5;
  3. Retry: python -m orchestration.jobs.settle_results
```

### generate_daily_summary failed

```
Usually a filesystem permission or disk-space issue.
Actions:
  1. Check storage/daily_summaries/ exists and is writable
  2. Retry: python -m orchestration.jobs.generate_daily_summary
```

---

## 4. After fixing — re-run pipeline

```bash
# Full re-run (creates a new DailyPipelineRun row)
python -m orchestration.daily_pipeline --triggered-by manual

# Or targeted job(s) only
python -m orchestration.jobs.<job_name>
```

---

## 5. Escalation

If a hard-dep failure cannot be resolved within 24 hours:
- Log the incident in this file (bottom of page) with date and root cause.
- Do not generate recommendations until the source data is confirmed fresh.
- Consider disabling the cron job temporarily: `crontab -e` on server computer.

---

## Incident log

| Date | Job | Cause | Resolution |
|------|-----|-------|-----------|
| (add entries here) | | | |
