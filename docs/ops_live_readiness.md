# Live-Readiness Checklist

Decision-support checklist for evaluating readiness for a restricted
manual micro-trial with real money.

**This document does NOT authorise live betting.**
The system does not support automated real-money bet placement.
All live bets, if attempted, must be placed manually by the operator.

---

## Automated readiness report

```bash
curl http://localhost:8000/dashboard/readiness
```

This runs `evaluation/live_readiness.py` and returns a JSON report.

Overall statuses:
- `ready` — all checks pass or warn (no fails)
- `marginal` — at least one warn, no fails
- `not_ready` — at least one fail

**Never proceed with a live trial if status is `not_ready`.**

---

## Manual checklist

Complete this checklist in addition to the automated report.

### A. Paper-trading performance

- [ ] At least **100 settled paper bets** reviewed
- [ ] Backtest ROI is not catastrophically negative (> -0.10 per unit staked)
- [ ] Hit rate is within plausible range (40–65% for H2H sports betting)
- [ ] Max paper-trade drawdown < 25% of starting bankroll
- [ ] No evidence of look-ahead bias in backtesting

### B. Model quality

- [ ] Most recent Brier score < 0.22
- [ ] ECE (expected calibration error) < 0.06
- [ ] Model selection uses best performer, not just most recent
  - **TODO**: update `generate_recommendations._load_best_model` to use Brier score
- [ ] At least 2 full AFL seasons of training data

### C. Data pipeline reliability

- [ ] Pipeline ran successfully every day for last 14 days
- [ ] No hard-dep failures in last 7 days
- [ ] Odds freshness confirmed < 26h before each round
- [ ] AFL fixture freshness confirmed < 48h
- [ ] The Odds API quota has not been exhausted this month
- [ ] TAB bookmaker confirmed present in API responses

### D. Code and system quality

- [ ] All `CRITICAL_TODOS` in `evaluation/live_readiness.py` resolved
- [ ] `paper_trade_only=True` in `config/settings.py` (confirm intentional before any override)
- [ ] No automated bet placement code exists anywhere in the codebase
  - Confirm: `grep -r "place_bet\|execute_bet\|live_bet" --include="*.py" .`
- [ ] Recommendation stake fractions are capped at `max_kelly_fraction=0.05`
- [ ] Edge threshold `min_edge_threshold` is >= 0.03

### E. Operational readiness

- [ ] 30-day review completed and documented in `ops_30day_review.md`
- [ ] TAB account open with verified identity (if proceeding)
- [ ] Starting bankroll decided (recommend: ≤ amount comfortable losing entirely)
- [ ] Micro-trial rules agreed:
  - Max bets per week: ___
  - Max stake per bet (dollars): ___
  - Stop-loss (abandon if bankroll drops below): ___
  - Review frequency: ___

### F. Decision gate

- [ ] All automated checks: `ready` or `marginal` (no `not_ready`)
- [ ] All manual checks above: ticked
- [ ] Reviewed by operator (you), not just the automated report
- [ ] Decision recorded below with date and rationale

---

## Decision record

| Date | Automated status | Manual checks complete | Decision | Rationale |
|------|-----------------|----------------------|----------|-----------|
| (first fill-in date) | | | Continue paper trading | Insufficient sample size |

---

## Micro-trial constraints (if proceeding)

If all gates are passed and operator decides to proceed:

1. Paper trading continues in parallel — do NOT disable it.
2. Real bets placed manually only — copy recommendation details from dashboard.
3. Stake no more than `max_kelly_fraction` × designated live bankroll.
4. Review outcomes weekly.
5. Return to paper-trading-only if any of these conditions occur:
   - Live bankroll drawdown > 20%
   - Three consecutive losing rounds
   - Any pipeline reliability issue
   - Any data quality concern

---

## What this system does NOT do

- It does **not** place bets automatically.
- It does **not** connect to any bookmaker API for bet placement.
- It does **not** manage a real-money account.
- The `paper_trade=True` flag on every Recommendation record is a hard constraint.
