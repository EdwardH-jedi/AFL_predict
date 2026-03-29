# 30-Day Paper Trading Review

Template for periodic review of the paper-trading system.
Run this roughly every 30 days, or before considering a live trial.

---

## 1. Pull summary data

```bash
# Launch API
make serve

# Core endpoints
curl http://localhost:8000/dashboard/bankroll?days=30
curl http://localhost:8000/dashboard/recommendations?limit=100
curl http://localhost:8000/dashboard/no-bet-days?days=30
curl http://localhost:8000/dashboard/pipeline?days=30
curl http://localhost:8000/dashboard/readiness
```

Or run the backtest report:

```bash
make backtest
```

---

## 2. Metrics to record

Fill in each time you run this review.

| Metric | This period | Previous period | Direction |
|--------|------------|-----------------|-----------|
| Date range | | | — |
| Total bets placed | | | |
| Hit rate (win%) | | | |
| Average edge | | | |
| Total ROI (units) | | | |
| Max drawdown | | | |
| No-bet days | | | |
| Pipeline failures | | | |
| Stale-data warnings | | | |
| Brier score (backtest) | | | |
| ECE (backtest) | | | |

---

## 3. Decision framework

Answer each question:

### 3a. Is the sample size sufficient?
- Minimum: 100 settled bets
- Current: ___
- ☐ Yes / ☐ No — if No, continue paper trading

### 3b. Is the strategy profitable or at least break-even?
- ROI >= -0.05 (allowing for variance): ☐ Yes / ☐ No
- If deeply negative (< -0.20 ROI), investigate model or edge-detection issues

### 3c. Is the drawdown acceptable?
- Max drawdown < 25%: ☐ Yes / ☐ No
- If No, pause and review recent losing bets — look for systematic errors

### 3d. Is calibration stable?
- Brier score < 0.22 (better than coin flip at 0.25): ☐ Yes / ☐ No
- ECE < 0.06: ☐ Yes / ☐ No

### 3e. Is the pipeline reliable?
- < 2 hard-dep failures in the period: ☐ Yes / ☐ No
- No recurring stale-data issues: ☐ Yes / ☐ No

### 3f. Any systematic errors?
Review:
- Bets placed on non-AFL matches: ☐ None found
- Odds used were clearly wrong: ☐ None found
- Recommendations generated with stale data: ☐ None found

---

## 4. Actions

Based on the review, choose one:

| Decision | Condition |
|----------|-----------|
| **Continue paper trading** | Any item above is No, or sample < 100 |
| **Run live-readiness check** | All items are Yes |
| **Pause and investigate** | Drawdown > 25% or ROI < -0.20 |
| **Retrain models** | Brier > 0.22 or calibration unstable |

---

## 5. Live-readiness check (if applicable)

Only proceed here after completing step 4 and deciding conditions are met.

```bash
curl http://localhost:8000/dashboard/readiness
```

See `ops_live_readiness.md` for full checklist.

---

## Review history

| Date | Sample N | ROI | Drawdown | Outcome |
|------|----------|-----|---------|---------|
| (add entries here) | | | | |
