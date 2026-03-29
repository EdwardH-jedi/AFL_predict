# Daily Operations Runbook

Routine for each AFL match day and non-match day.

---

## 1. Scheduled run (server computer, ~08:00 AEST)

The cron job runs automatically:

```
python -m orchestration.daily_pipeline --triggered-by cron
```

This executes jobs in order:
1. `check_data_freshness` — soft, always runs
2. `ingest_afl` — hard dep, retryable
3. `ingest_tab_odds` — hard dep, retryable
4. `build_features` — hard dep
5. `generate_recommendations` — soft
6. `settle_results` — soft
7. `generate_daily_summary` — soft, writes `storage/daily_summaries/YYYY-MM-DD.json`

---

## 2. Morning review (main computer or MacBook, ~09:00 AEST)

Start the API server if not already running:

```bash
make serve          # or: uvicorn api.main:app --port 8000
```

Open in browser or curl:

```
http://localhost:8000/dashboard/summary         # combined daily view
http://localhost:8000/dashboard/pipeline        # pipeline run status
http://localhost:8000/dashboard/recommendations # latest recommendations
http://localhost:8000/dashboard/freshness       # data age warnings
http://localhost:8000/dashboard/bankroll        # bankroll trend
http://localhost:8000/docs                      # Swagger UI
```

Or inspect the artifact directly:

```bash
cat storage/daily_summaries/$(date +%Y-%m-%d).json | python -m json.tool
```

---

## 3. What to check each morning

| Check | OK state | Action if not OK |
|-------|----------|-----------------|
| Pipeline status | `success` | See `ops_failed_pipeline.md` |
| Odds freshness | age < 26h | See `ops_stale_data.md` |
| AFL freshness | age < 48h | Run `make ingest-afl` manually |
| Recommendations | 0–3 recs pending | Normal on non-match days |
| Bankroll drawdown | < 25% | Review recent bets; pause if > 25% |
| No-bet day | Normal | Log reason for review |

---

## 4. Weekly tasks

- **Monday**: Review 7-day pipeline failure rate (`/dashboard/pipeline?days=7`).
- **Every ~4 weeks**: Run 30-day review — see `ops_30day_review.md`.
- **Before each round**: Confirm odds are present for all upcoming matches (`/dashboard/freshness`).

---

## 5. Manual pipeline re-run

If the cron run failed or was incomplete:

```bash
# On server computer
python -m orchestration.daily_pipeline --triggered-by manual

# Or individual jobs
make ingest-afl
make ingest-odds
make build-features
```

---

## 6. Non-match days

No recommendations will be generated on non-match days.
The pipeline still runs (data collection, settlement of any pending bets).
`/dashboard/no-bet-days` tracks these days.

---

## Notes

- All betting is paper-trade only. `paper_trade=True` on every recommendation.
- Never remove the `paper_trade_only=True` check in `config/settings.py` without a full readiness review.
- The `generate_daily_summary` job is the last job — if it fails, the pipeline is still `partial_failure` but all prior jobs completed.
