# Stale Data Runbook

How to detect, diagnose, and recover from stale data conditions.

---

## Thresholds (configurable in .env)

| Data source | Stale after | Setting key |
|-------------|-------------|-------------|
| Odds snapshots | 26 hours | `ODDS_FRESHNESS_HOURS` |
| AFL fixtures | 48 hours | `AFL_FRESHNESS_HOURS` |

---

## Detection

### Via API

```bash
curl http://localhost:8000/dashboard/freshness
```

Response fields:
- `odds_stale: true` — odds are too old
- `afl_stale: true` — AFL fixture data is too old
- `warnings: [...]` — human-readable summary

### Via daily artifact

```bash
cat storage/daily_summaries/$(date +%Y-%m-%d).json | python -m json.tool | grep -A5 freshness
```

### Via pipeline check_data_freshness job

The `check_data_freshness` job runs first in each daily pipeline.
It logs warnings and stores results; check the server logs or the pipeline artifact.

---

## Recovery

### Stale odds

```bash
# Re-run odds ingestion
make ingest-odds

# Verify
curl http://localhost:8000/dashboard/freshness
```

If The Odds API quota is exhausted:
- Do NOT generate recommendations for today.
- Note the date in the incident log (`ops_failed_pipeline.md`).
- Quota resets monthly — check dashboard at the-odds-api.com.

### Stale AFL fixtures

```bash
# Re-run AFL ingestion (fetches latest round)
make ingest-afl

# Or specific season/round
python -m orchestration.jobs.ingest_afl --season 2025 --round 5
```

### Upcoming matches without odds

If `/dashboard/freshness` reports upcoming matches with no odds:
1. Check if the match is pre-season or a bye (no odds is expected).
2. If it is a genuine upcoming match, run `make ingest-odds` to fetch odds.
3. If the bookmaker doesn't have odds yet, wait and retry closer to game day.

---

## Preventing stale data

- The cron job on the server computer runs at 08:00 AEST daily (see `ops/crontab_server.txt`).
- If the server is offline overnight, run the pipeline manually the next morning.
- Odds change daily — always ingest odds on match day mornings.
- AFL fixture updates (scores, results) are available after each round completes.

---

## Data freshness in recommendations

Recommendations are only generated if both AFL data and odds data are fresh.
If either is stale, the `check_data_freshness` job will log warnings,
and `generate_recommendations` may produce no output or stale predictions.

**Never rely on recommendations generated from stale odds.**

---

## Monitoring cadence

| Frequency | Action |
|-----------|--------|
| Daily | Check `/dashboard/freshness` or morning artifact |
| Weekly | Review `check_data_freshness` warnings in last 7 days |
| Monthly | Confirm API quota not exhausted |
