# Weekly Review Framework

**Purpose:** Structured 1–2 week review of paper trading results.  
**Audience:** Single operator reviewing their own system.  
**Frequency:** End of week 1, end of week 2, then every AFL round thereafter.

This framework exists to answer one question at the end of each review:
**Is the data we are accumulating clean, consistent, and pointing toward signal — or is it
telling us something is broken?**

It is not a trading decision framework. Do not use a 1–2 week review to adjust thresholds,
tune the model, or draw strong conclusions. Use it to confirm the system is operating
correctly and to begin building intuition about the data.

---

## 0. Before you start

Gather the inputs:

```bash
# Start API server if not running
make serve

# Confirm summary artifacts exist for all days in the review window
ls storage/daily_summaries/

# Open the paper trading log for the period
cat storage/paper_trading_log.md
```

Retrieve operating data for the review window (replace `N` with days in the window, e.g. 7 or 14):

```bash
curl -s "http://localhost:8000/dashboard/summary"           | python -m json.tool
curl -s "http://localhost:8000/dashboard/bankroll?days=N"   | python -m json.tool
curl -s "http://localhost:8000/dashboard/pipeline?days=N"   | python -m json.tool
curl -s "http://localhost:8000/dashboard/recommendations?limit=100" | python -m json.tool
curl -s "http://localhost:8000/dashboard/no-bet-days?days=N" | python -m json.tool
curl -s "http://localhost:8000/dashboard/freshness"          | python -m json.tool
curl -s "http://localhost:8000/dashboard/readiness"          | python -m json.tool
```

---

## 1. Tier-level performance review

**What this answers:** Are recommendations with larger claimed edge outperforming those with
smaller edge? Do different edge levels show different hit rates?

### How to compute

The system does not yet produce automatic tier breakdowns. Extract from
`/dashboard/recommendations`:

Group recommendations by edge size into three buckets:

| Tier | Edge range | Description |
|------|------------|-------------|
| Strong | edge >= 0.08 | High-confidence picks |
| Standard | 0.04 <= edge < 0.08 | Threshold clearances |
| Marginal | min_edge <= edge < 0.04 | Near-threshold picks |

For each tier, record:
- **N bets** in tier
- **Hit rate** (bets won / bets placed)
- **ROI** (net profit / total staked)
- **Avg stake fraction** (Kelly fraction)

### What to look for

- Strong tier should have a higher hit rate and ROI than Marginal tier, **on average over
  many weeks**. After 1–2 weeks, sample size per tier is too small for conclusions.
- If Marginal picks are consistently winning and Strong picks are losing, this suggests the
  edge estimates are poorly calibrated — flag for the monthly review.
- If all tiers have hit rates near 50% with negative ROI, that is expected for low-N weeks —
  do not act on it.

### 1–2 week interpretation rule

> With fewer than 30 bets per tier, treat all tier differences as noise.
> Record the numbers but draw no conclusions.

---

## 2. Edge bucket review

**What this answers:** What does the raw distribution of edge values look like? Is the system
finding genuine differentiation, or clustering near the threshold?

### How to compute

From `/dashboard/recommendations`, collect `stake_fraction` and implied edge for all
recommendations in the window. Group into bins: [0.03, 0.05), [0.05, 0.08), [0.08, 0.12), [0.12+).

Record:
- Count of bets per bucket
- Mean edge per bucket
- Hit rate per bucket (once settled)

### What to look for

- **Heavy clustering near `min_edge_threshold`:** Most bets just clearing the threshold suggests
  the edge signal is weak. This is not necessarily bad but means the threshold is doing real work
  — raises the stakes for threshold tuning decisions.
- **No bets in high-edge buckets:** If the 0.12+ bucket is always empty, the model is rarely
  confident. Monitor whether this changes after model improvements.
- **Erratic edge distribution week-to-week:** Suggests odds data quality issues or model
  instability. Check stale-data days for correlation.

---

## 3. Stale odds review

**What this answers:** How often were recommendations generated from odds that were not
fresh? Were any stale-odds recommendations included in the performance record in error?

### How to compute

From `storage/paper_trading_log.md`, count:
- Days marked `[STALE-DATA DAY]`
- Days where `freshness.odds_stale = true` in the JSON artifact but recommendations were
  still generated

Cross-reference: did any bet outcome land on a stale-data day?

```bash
# Check freshness warnings per day across the window
for f in storage/daily_summaries/*.json; do
    python -c "
import json, sys
d = json.load(open('$f'))
if d.get('freshness', {}).get('odds_stale'):
    print(d['date'], 'ODDS STALE', d['freshness'].get('warnings'))
" 2>/dev/null
done
```

### What to look for

- **Any bet counted during a stale-odds day is invalid** — remove it from performance calcs.
- More than 2 stale-odds days per week indicates a collection problem. Investigate API quota
  and cron scheduling.
- If `upcoming_without_odds > 0` frequently, the odds collector is missing matches.

---

## 4. No-bet frequency review

**What this answers:** How often is the system declining to bet? Is the no-bet rate reasonable
or is the threshold so strict that the system is nearly never active?

### How to compute

```bash
curl -s "http://localhost:8000/dashboard/no-bet-days?days=N" | python -m json.tool
```

Also count from `storage/paper_trading_log.md`:
- Total days in window
- Match days (days when at least one AFL match was played)
- No-bet days among match days
- Reason breakdown (threshold, no odds, no upcoming matches)

Compute: **no-bet rate = no-bet match days / total match days**

### Interpretation guide

| No-bet rate | Interpretation |
|-------------|----------------|
| < 30% | System is active — reasonable |
| 30–60% | Threshold may be slightly restrictive — normal early on |
| 60–80% | Threshold is likely too high OR edge signal is weak — review after 4 weeks |
| > 80% | System is nearly always declining — threshold or model calibration needs investigation |

### What to look for

- A high no-bet rate is preferable to a low one at this stage. Missing bets that would have
  won is far less damaging than placing bets on noise.
- If no-bet rate is 0% (the system always bets), something is wrong — edge threshold may have
  silently been set to 0 or a misconfiguration occurred.
- Track no-bet rate week-over-week. A sudden increase may indicate a model drift or odds
  structure change. A sudden decrease may indicate an edge threshold that was accidentally lowered.

---

## 5. Drawdown review

**What this answers:** Is the bankroll deteriorating? Is the rate of loss acceptable given
the sample size?

### How to compute

```bash
curl -s "http://localhost:8000/dashboard/bankroll?days=N" | python -m json.tool
```

From the response, record:
- `current_balance`
- `peak_balance`
- `drawdown` (current drawdown from peak)
- Trend: improving, flat, or worsening over the window

### Drawdown thresholds

| Drawdown | Interpretation | Action |
|----------|---------------|--------|
| < 10% | Normal variance — no action | None |
| 10–20% | Elevated — monitor closely | Note in log; review edge quality |
| 20–25% | Warning zone | Do not increase stake; consider pausing |
| > 25% | Hard pause threshold | Stop paper trading; investigate |

### What to look for

- **A 2-week drawdown in AFL is highly likely even for a sound strategy.** Sample sizes of
  10–30 bets produce large variance in hit rate and P&L. Do not interpret a 15% drawdown as
  evidence the strategy is wrong.
- **Consistent downward trajectory** across consecutive weeks is more meaningful than a
  single bad week.
- **Drawdown exceeding 20% on a per-round basis** (not cumulative from start) is a stronger
  warning sign than a slow grind down from early losses.
- Check whether losses concentrate on a particular match type, team, or venue — if so, note
  it for the monthly review.

---

## 6. CLV / CLV proxy review

**What this answers:** Are our picks moving in the direction we predicted (odds drifting
toward us)? This is a process quality signal, not just an outcome signal.

### Current limitation

The system does not currently track closing-line odds (odds at match kick-off). The
`recommended_odds` stored in `Recommendation` is the odds at time of recommendation, not the
final odds.

**CLV proxy available today:** Compare the recommended odds of winning bets vs. losing bets.
If winners had, on average, shorter odds than losers for the same edge tier, that is a sign
of adverse selection (we are taking short-odds bets that look like value but are not).

### Approximate CLV check

For each settled recommendation:
1. Note `recommended_odds` and `side`
2. Note whether the bet won
3. Group by edge tier (see Section 1)

Look for: are we more often correct when we take longer odds vs. shorter odds?

### Future instrumentation needed

To do a proper CLV review, the system needs to:
1. Store the last-available odds snapshot before match kick-off
2. Compute: `CLV = (final_odds - recommended_odds) / recommended_odds`
3. Report CLV per recommendation

A positive average CLV means the market moved in our favour after we "placed" the bet —
a sign of genuine edge. Negative CLV means the market moved against us — a warning sign.

**Flag this for implementation after 4 weeks of paper trading data is available.**

---

## 7. Data integrity issue review

**What this answers:** Were there any silent data quality failures during the week? Are
team names, odds, or fixture data getting corrupted or miscounted?

### Checks to run

**7a. Team name normalisation**

```bash
# After running ingest, check for unknown team aliases in logs
grep "unknown" storage/logs/*.log 2>/dev/null || echo "Check loguru output manually"
```

The `team_normalizer.py` calls `get_unknown_aliases()` at the end of each odds ingest.
Any unknown alias means odds were likely discarded for that match.

**7b. Duplicate recommendations**

Check `/dashboard/recommendations` for the window. Look for:
- Same match appearing twice (deduplication failure)
- Both home and away recommended for the same match (normally only one side passes the threshold)
- Recommendations with `paper_trade = false` (should never occur)

**7c. Feature leakage check (weekly)**

The system logs `ERROR` for leakage violations in `features/validators.py`. Scan logs:

```bash
grep -i "leakage" storage/logs/*.log 2>/dev/null
```

If any leakage errors are found: **do not count any recommendations from that day**. Treat
as an integrity-failure day and note in `storage/paper_trading_log.md`.

**7d. Bet outcome settlement check**

Confirm that all bets from match days more than 48 hours ago have been settled:

```bash
curl -s "http://localhost:8000/dashboard/recommendations" | python -m json.tool | grep '"status"'
```

Any `"status": "pending"` for a match more than 48 hours ago indicates a settlement failure.
Run `make pipeline` and check `settle_results` job status.

### What to look for

- Any integrity failure invalidates the affected day for performance purposes.
- Repeated integrity failures of the same type indicate a systematic bug — prioritise fixing
  before continuing paper trading.

---

## 8. Recommendation explanation usefulness review

**What this answers:** When you look at a recommendation, can you understand *why* the system
made it? Is the explanation useful for operator decision-making?

### How to review

Pull the most recent 5–10 recommendations from `/dashboard/recommendations` and for each, ask:

| Question | Expected answer |
|----------|----------------|
| Is the match clearly identified (teams, date)? | Yes |
| Is the side (home/away) clearly stated? | Yes |
| Is the recommended odds shown? | Yes |
| Is the edge value shown? | Yes |
| Is the stake fraction shown? | Yes |
| Can I understand why this match was recommended vs. not? | Ideally yes |
| Is the explanation enough to cross-check against TAB manually? | Yes |

### Known gaps at this stage

The current recommendation output (`/dashboard/recommendations`) provides:
- Match ID, teams, date
- Side, odds, stake fraction, paper trade flag, status

It does **not** currently provide:
- Which model generated the prediction
- The confidence breakdown (home_win_prob, away_win_prob)
- The edge value (probability - bookmaker implied)
- Why this match was selected over others

These are available in the database (`Prediction` table, `home_edge`, `away_edge` fields)
but are not surfaced in the dashboard endpoint.

**Note in weekly log:** Is the lack of per-recommendation explanation causing any difficulty
in daily review? If yes, flag this for the first iteration improvement.

---

## Weekly review record

Complete this table at the end of each review. Keep one row per week.

| Week | Dates | Match days | Bet days | No-bet days | Stale-data days | Integrity failures | Bets placed | Hit rate | ROI (units) | Peak drawdown | Notes |
|------|-------|-----------|---------|------------|----------------|-------------------|-------------|---------|-------------|--------------|-------|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| 3 | | | | | | | | | | | |
| 4 | | | | | | | | | | | |

---

## End-of-review decision

After completing all 8 sections, choose one:

| Decision | Condition |
|----------|-----------|
| **Continue paper trading — data clean** | All sections OK; no integrity failures; drawdown < 20% |
| **Continue paper trading — monitor closely** | 1–2 stale-data days; drawdown 15–20%; no-bet rate high |
| **Pause and investigate** | Drawdown > 25%; repeated integrity failures; CLV consistently negative |
| **Run 30-day review** | 30+ settled bets accumulated; 4 weeks complete; see `ops_30day_review.md` |

Do **not** use a 1–2 week review to make threshold changes. Wait for the 30-day review with
sufficient sample size before any parameter adjustments. See `docs/recommendation_quality_iteration.md`.

---

## Signal vs. noise guide

Use this to avoid over-reacting to early results:

| Observation | Likely signal or noise? | Wait before acting |
|-------------|------------------------|-------------------|
| 3 consecutive losses | Noise | 4+ weeks |
| 5 consecutive wins | Noise | 4+ weeks |
| Hit rate < 40% over 15+ bets | Early signal — monitor | 30+ bets |
| ROI < -0.20 over 20+ bets | Signal — investigate | Now |
| Drawdown > 25% | Signal — pause | Immediately |
| CLV consistently negative over 20+ bets | Signal — model issue | 20+ bets |
| No-bet rate > 80% on match days | Signal — threshold issue | 2+ weeks |
| Integrity failure on 2+ separate days | Signal — fix first | Immediately |
