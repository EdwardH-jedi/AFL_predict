# Paper Trading Operation Plan

**Period:** 2–4 weeks of disciplined paper trading before any real-money consideration.  
**Objective:** Accumulate a clean, honest record of model recommendations and outcomes to
support the first evidence-based review of system performance.

> This document is the authoritative daily checklist for the paper trading period.
> Follow it in order every day, even on non-match days.

---

## 0. Prerequisites (first-time setup, once only)

Before the first operating day:

```bash
# 1. Apply all pending DB migrations
make migrate

# 2. Confirm the API starts cleanly
make serve   # check http://localhost:8000/docs

# 3. Confirm the pipeline can run end-to-end
make pipeline

# 4. Confirm the daily summary artifact is written
ls storage/daily_summaries/
```

Verify `config/settings.py` has `PAPER_TRADE_ONLY=true` (or `.env` override).
**Never change this setting during the paper trading period.**

---

## 1. Daily run — Step A: Trigger the pipeline (~08:00–09:00 AEST)

```bash
# Automated (preferred — via cron on server computer)
# Cron fires: python -m orchestration.daily_pipeline --triggered-by cron

# Manual fallback (if cron failed or you are running on the main machine)
make pipeline
```

The pipeline runs these jobs in order:

| # | Job | Type | What it does |
|---|-----|------|-------------|
| 1 | `check_data_freshness` | soft | Warns if odds or AFL data is stale |
| 2 | `ingest_afl` | hard dep | Fetches latest AFL fixtures and results |
| 3 | `ingest_tab_odds` | hard dep | Fetches TAB H2H pre-match odds snapshots |
| 4 | `build_features` | hard dep | Rebuilds pre-match feature matrix |
| 5 | `generate_recommendations` | soft | Emits recommendations for upcoming matches |
| 6 | `settle_results` | soft | Settles any pending paper bets with known results |
| 7 | `generate_daily_summary` | soft | Writes `storage/daily_summaries/YYYY-MM-DD.json` |

A pipeline result of `success` or `partial_failure` (soft-job issue only) is acceptable.  
A result of `failed` (hard dep failure) requires intervention — see `ops_failed_pipeline.md`.

---

## 2. Daily run — Step B: Read the daily artifact (~09:00 AEST)

```bash
# Quick inspection
cat storage/daily_summaries/$(date +%Y-%m-%d).json | python -m json.tool

# Or via API (if serve is running)
curl -s http://localhost:8000/dashboard/summary | python -m json.tool
```

Key fields to check:

| Field | Acceptable state | Action if not acceptable |
|-------|-----------------|--------------------------|
| `pipeline.status` | `success` or `partial_failure` | See `ops_failed_pipeline.md` |
| `freshness.odds_stale` | `false` | See `ops_stale_data.md`; log as stale-data day |
| `freshness.afl_stale` | `false` | Run `make ingest-afl`; log if unresolved |
| `freshness.upcoming_without_odds` | `0` | Run `make ingest-odds`; note in daily log |
| `recommendations` | list (may be empty) | See Step C |
| `no_bet_day.is_no_bet_day` | `true` or `false` | Log accordingly — see Step D |
| `bankroll.drawdown` | `< 0.25` (25%) | Review recent bets; pause if ≥ 25% |

---

## 3. Daily run — Step C: Review recommendations before accepting them

**Never record a recommendation as acted-upon without completing this review.**

For each recommendation in today's output:

### C1 — Odds freshness check

Confirm `freshness.odds_stale` is `false`.  
If odds are stale, **do not count this recommendation** in the paper trading record.
Log as a stale-data day (see Step E).

### C2 — Match plausibility check

For each recommended match:
- Does the match exist and is the date/time plausible? (check AFL fixture source)
- Are both teams correctly named? (team normaliser can silently pass through unknowns)
- Is the match in the current round? (reject if `match_date` is in the past)

### C3 — Edge and stake sanity check

For each recommendation in the artifact:

| Field | Sanity check |
|-------|-------------|
| `side` | Must be `home` or `away` — reject if blank or null |
| `odds` | Must be > 1.01 — reject if implausible |
| `stake_fraction` | Must be ≤ 0.05 (5% Kelly cap) — flag if higher |
| `paper_trade` | Must be `true` — **reject and investigate if false** |
| `status` | Must be `pending` — not already settled |

If any check fails: **do not record the recommendation as valid today**.
Note the failure in the daily log file.

### C4 — Model source check

Check `pipeline.jobs` — confirm `generate_recommendations` completed.  
If it completed with `records_processed = 0` on a match day, note in the log.

---

## 4. Daily run — Step D: Record the day

Maintain a running daily log at `storage/paper_trading_log.md` (plain text, one entry per day).

### Match-day entry (recommendations present)

```
## YYYY-MM-DD  [MATCH DAY]
Pipeline: success | partial_failure
Recommendations: N (list match names and sides)
Accepted: N (after C1–C4 review)
Rejected: N (reason: <stale odds / plausibility / sanity check>)
Notes: <any other observation>
```

### No-bet day entry

```
## YYYY-MM-DD  [NO-BET DAY]
Pipeline: success | partial_failure
Reason: <no upcoming matches / edge below threshold / non-match day>
Notes: <optional>
```

### Stale-data day entry

```
## YYYY-MM-DD  [STALE-DATA DAY]
Pipeline: success | partial_failure | failed
Stale source: odds | AFL | both
Recommendations generated: yes (INVALID — not counted) | no
Recovery action taken: <describe>
Notes: <optional>
```

### Integrity-failure day entry

```
## YYYY-MM-DD  [INTEGRITY FAILURE]
Pipeline: failed
Failing job: <job name>
Error: <brief summary>
Recovery action: <describe>
Recommendations counted: 0 (pipeline failed — no valid output)
```

---

## 5. End-of-day check (optional but recommended on match days)

After odds close for the day (~match kick-off):

```bash
# Confirm bankroll state has not drifted from expected
curl -s http://localhost:8000/dashboard/bankroll | python -m json.tool

# Confirm all pending paper bets for today are still status=pending
# (settle_results only runs during the daily pipeline — not real-time)
curl -s http://localhost:8000/dashboard/recommendations | python -m json.tool
```

No action needed unless drawdown > 25% — in that case note in daily log and pause.

---

## 6. No-bet day handling

A no-bet day is **normal and expected**. Reasons include:

- Non-match week (bye round or off-season)
- All upcoming matches have edge below `min_edge_threshold`
- Odds were stale and recommendations were suppressed
- Pipeline failed to generate recommendations

**Record every no-bet day** in `storage/paper_trading_log.md`.  
Do not attempt to force recommendations on no-bet days.  
Track cumulative no-bet frequency — if >70% of AFL match days are no-bet, review the
edge threshold in the first weekly review.

---

## 7. Stale-data day handling

A stale-data day occurs when either odds or AFL fixture data fails the freshness check.

**Steps:**

1. Note `freshness.odds_stale` and `freshness.afl_stale` from the daily artifact.
2. Attempt recovery (`make ingest-odds` / `make ingest-afl`).
3. If recovery succeeds before the first match of the day, the day may still produce valid recommendations — re-run `make pipeline`.
4. If recovery fails (API quota exhausted, source unavailable), classify the day as
   a stale-data day and **do not count any recommendations** generated from it.
5. Log the event and recovery outcome in `storage/paper_trading_log.md`.

A stale-data day does not count as a paper trading signal day — exclude it from
performance calculations in the weekly review.

---

## 8. Weekly tasks

On Monday morning (or the first day of each new AFL round):

1. Check pipeline health for the past 7 days:
   ```bash
   curl -s "http://localhost:8000/dashboard/pipeline?days=7" | python -m json.tool
   ```
2. Count: valid signal days / total match days this week.
3. Count: stale-data days and no-bet days.
4. Review `storage/paper_trading_log.md` entries for the week.
5. Confirm `storage/daily_summaries/` has a file for every day in the week.
6. If drawdown reached 20–24%: document in the log and flag for weekly review.

See `docs/weekly_review_framework.md` for the full weekly review protocol.

---

## 9. What must NOT happen during the paper trading period

- Do not change `min_edge_threshold`, `max_kelly_fraction`, or `PAPER_TRADE_ONLY` without documenting the change and reason.
- Do not selectively exclude losing days from the paper trading log.
- Do not count recommendations generated on stale-data days.
- Do not re-run the pipeline on a past date to retroactively generate recommendations.
- Do not interpret short streaks (positive or negative) as evidence — wait for the weekly review.

---

## 10. Summary outputs to check each day

| Output | Location | How to inspect |
|--------|----------|---------------|
| Daily JSON artifact | `storage/daily_summaries/YYYY-MM-DD.json` | `cat ... \| python -m json.tool` |
| Pipeline status | API `/dashboard/pipeline` | curl or browser |
| Recommendations | API `/dashboard/recommendations` | curl or browser |
| Freshness status | API `/dashboard/freshness` | curl or browser |
| Bankroll trend | API `/dashboard/bankroll` | curl or browser |
| Daily log | `storage/paper_trading_log.md` | text editor |

---

## Appendix: Quick-reference commands

```bash
# Run the daily pipeline manually
make pipeline

# Check freshness only
make freshness-check

# Regenerate today's summary artifact
make daily-summary

# Re-ingest odds (manual recovery)
make ingest-odds

# Re-ingest AFL fixtures (manual recovery)
make ingest-afl

# Run live-readiness report (weekly or on demand)
make readiness

# Start API server
make serve
```
