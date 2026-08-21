# Recommendation Quality Iteration

**Purpose:** Define how to change recommendation-quality parameters safely, after evidence
accumulates from paper trading.

**Governing principle:** Every parameter change must be driven by a specific evidence
threshold. No parameter should be changed in response to a streak. No parameter should be
changed without re-running the backtest on the updated setting before deploying it.

---

## 0. When is it safe to consider a change?

Iteration is only permitted after:

1. The 30-day paper trading review has been completed (`docs/ops_30day_review.md`).
2. At least 30 settled paper bets exist in the database.
3. No data integrity failures are outstanding (leakage, stale-data days not yet resolved).
4. The backtest infrastructure is working cleanly (`make backtest` runs end-to-end).

Before that point, the parameters are frozen. A short positive streak is not evidence.
A short negative streak is not evidence. See the "what must never change impulsively"
section at the end of this document.

---

## 1. Edge threshold tuning

**Parameter:** `MIN_EDGE_THRESHOLD` in `.env` (default: `0.03`)  
**Effect:** Controls the minimum `model_prob - bookmaker_implied_prob` required to emit a
recommendation. Raising it produces fewer but higher-conviction bets. Lowering it produces
more bets from weaker signals.

### Evidence required to change

| Direction | Evidence required |
|-----------|-----------------|
| Raise threshold | >= 30 settled bets AND avg_edge on losing bets is consistently near threshold (e.g., mean losing edge < 0.04) AND no-bet rate is acceptable (< 60%) |
| Lower threshold | >= 50 settled bets AND positive ROI at current threshold AND new threshold validated in backtest shows no degradation in Brier or hit_rate |

### Change process

1. Run the backtest at the proposed new threshold:
   ```bash
   make backtest ARGS="--edge-threshold 0.05"
   ```
2. Compare `roi`, `hit_rate`, `n_bets` vs. current threshold across all folds.
3. If the new threshold produces worse or equal ROI and fewer bets: do not change.
4. If it produces better hit_rate with acceptable n_bets: document the comparison and change.
5. Update `.env`: `MIN_EDGE_THRESHOLD=<new value>`
6. Record the change date and reason in `storage/paper_trading_log.md`.

### What a valid change looks like

```
Change: MIN_EDGE_THRESHOLD 0.03 → 0.05
Date: YYYY-MM-DD
Evidence: 52 settled bets. Backtest comparison showed hit_rate improved from 0.51 to 0.56
  at threshold 0.05. n_bets decreased from 48 to 31 per season — acceptable.
  No-bet rate at new threshold: 55% — within acceptable range.
Backtest run: storage/backtest_results/backtest_XXXXXXXX.json
```

### What not to do

- Do not raise the threshold after a losing week without backtest evidence.
- Do not lower the threshold to generate more bets because the system is quiet.
- Do not tune threshold up AND down in consecutive weeks — pick a direction after accumulating data.

---

## 2. Confidence threshold tuning

**Parameter:** No separate confidence threshold currently exists.  
The system uses edge (probability difference) as the sole selection criterion.

A confidence threshold would be a minimum on the raw `model_prob` itself — e.g., only
recommend if `home_win_prob >= 0.60`. This is distinct from edge.

### Should a confidence threshold be added?

**Not yet.** Adding a second filter before sufficient data exists risks masking the edge
signal with noise. The edge threshold already does the work of selecting high-conviction bets.

### Evidence required to add a confidence threshold

- >= 60 settled bets
- Analysis showing that bets with `model_prob` below some level (e.g., 0.52–0.58) have
  systematically worse outcomes than bets above it, even controlling for edge
- The pattern holds across at least two separate AFL rounds (not a single round's data)

### If added, the change process is the same as edge threshold tuning:

1. Backtest the new filter: does it improve hit_rate and ROI without collapsing n_bets?
2. Document the comparison.
3. Deploy only if improvement is demonstrated across multiple backtest folds.

---

## 3. Freshness window adjustments

**Parameters:**
- `ODDS_FRESHNESS_HOURS` (default: `26`)
- `AFL_FRESHNESS_HOURS` (default: `48`)

These thresholds control when a day is classified as a stale-data day.

### Guidance

These are **operational thresholds**, not model parameters. They should be changed only if:

- The odds collection cadence changes (e.g., you switch from daily to twice-daily collection)
- Experience shows the current threshold is generating false positives (flagging fresh data
  as stale) or false negatives (passing stale data as fresh)

### Change process

1. Check the weekly stale-data count from `storage/paper_trading_log.md`.
2. If stale-data days occur > 2 times/week consistently, investigate whether the **pipeline
   schedule** is the problem first (i.e., run the collection earlier) before adjusting the threshold.
3. If adjusting the threshold is genuinely needed, lower/raise by 2–4 hours at a time and
   verify the freshness check output changes as expected:
   ```bash
   make freshness-check
   ```
4. Never raise `ODDS_FRESHNESS_HOURS` above 36 — odds more than 36 hours old are not
   reliable for pre-match recommendations in a market that moves daily.

### What not to do

- Do not raise the freshness window to avoid recording stale-data days — that would silently
  corrupt the paper trading record.
- Do not lower freshness thresholds so aggressively that valid data is classified as stale.

---

## 4. Exclusion rule adjustments

**Current exclusion rules (implicit in the pipeline):**

| Rule | Where enforced |
|------|---------------|
| Only upcoming (unsettled) matches are considered | `generate_recommendations.py`: `df[df["home_win"].isna()]` |
| Both odds and features must be present | Feature builder returns NaN rows if data is missing |
| Paper trade only | `paper_trade=True` is hardcoded on every recommendation |
| Edge must clear threshold | `home_edge >= settings.min_edge_threshold` |

### Adding a new exclusion rule

Valid reasons to add an exclusion rule:
- Matches with stale odds are slipping through and producing invalid recommendations
- A specific match type (e.g., pre-season, finals) shows systematically different behaviour
  that skews the paper trading record
- A team name normalisation failure is producing bad recommendations

**Process for adding an exclusion:**

1. Identify the specific failure mode from the daily log or weekly review.
2. Write a filter in `orchestration/jobs/generate_recommendations.py` with a comment explaining
   the reason.
3. Backtest with the filter applied to confirm it does not degrade signal on historical data.
4. Record the change and reason in `storage/paper_trading_log.md`.

### What not to do

- Do not add exclusion rules based on team, venue, or other market-structural intuition
  without evidence — this is the path to retrofitting bias.
- Do not exclude finals from recommendations without first checking whether their edge
  distribution is meaningfully different from regular season games.
- Do not add "confidence" exclusions (e.g., exclude bets where the model is uncertain)
  without a clear, evidence-backed rationale — uncertainty is already priced into Kelly sizing.

---

## 5. Recommendation tier boundary adjustments

**Current state:** No formal tier boundaries exist in the code. Tiers are defined in
`docs/weekly_review_framework.md` as an analysis concept only.

### If tiers are formalised in code

Tier boundaries translate to different stake-sizing multipliers or different display groupings.
They should not be changed more often than once per 30-day review period.

**Evidence required to adjust tier boundaries:**

- >= 60 settled bets
- At least 10 bets per tier you want to evaluate
- Backtest confirms the tier boundary produces meaningful hit_rate differentiation
  (e.g., Strong tier hit_rate > Standard tier by 5+ percentage points)

**Process:** Same as edge threshold — backtest first, document comparison, then deploy.

### What not to do

- Do not tighten or loosen tier boundaries to make the high-confidence tier look better
  retroactively.
- Do not add a third tier to split weak picks if the split produces tiers with fewer than
  10 bets — too small to interpret.

---

## 6. Evidence required before changing any rule

All parameter changes follow the same three-gate process:

### Gate 1 — Minimum data threshold

| Change type | Minimum settled bets |
|-------------|---------------------|
| Edge threshold | 30 |
| Freshness windows | N/A (operational — use judgement) |
| Exclusion rules | 20 (enough to observe the failure pattern) |
| Confidence filter (new) | 60 |
| Tier boundaries | 60 |
| Kelly fraction cap | 100 (never reduce below 100 settled bets) |

### Gate 2 — Backtest validation

Run `make backtest` with the proposed change applied (edit settings in `.env` or pass as
CLI argument). The change must show at least one of:

- Improved hit_rate by >= 0.03 percentage points
- Improved ROI by >= 0.02 units
- Reduced ECE by >= 0.005

with no meaningful degradation in `n_bets` (drop of > 40% in bet count is a red flag).

### Gate 3 — Documentation

Before deploying, write an entry in `storage/paper_trading_log.md`:

```
PARAMETER CHANGE: <parameter name>
Old value: <X>
New value: <Y>
Date: YYYY-MM-DD
Evidence: <brief summary of what you observed>
Backtest result file: storage/backtest_results/<filename>.json
Fold comparison: <metric before> → <metric after>
```

There is no gate 4. If the change passes these three gates, deploy it. If you find yourself
inventing a fourth reason not to deploy it, you may be overfitting in the other direction.

---

## 7. What must never be changed impulsively

### After a winning streak

- Do not lower `MIN_EDGE_THRESHOLD` to generate more volume while the system is winning.
  A winning streak is high variance, not validated edge expansion.
- Do not raise `MAX_KELLY_FRACTION` above 0.05 based on a positive run.
  The cap is a risk management rule, not a performance parameter.
- Do not "promote" the system to live trials based on 2–3 weeks of wins.
  The minimum bar for live trial consideration is in `docs/ops_live_readiness.md`.

### After a losing streak

- Do not raise `MIN_EDGE_THRESHOLD` after losses to "tighten quality".
  Threshold changes based on recent losses are the textbook definition of overfitting to
  recent noise.
- Do not add team-specific or venue-specific exclusion rules after a bad round.
  One AFL round is 9 matches — far too small to identify a genuine pattern.
- Do not retrain the model after losses without running the backtest first.
  Retraining in response to recent performance without evidence is overfitting the model
  to the test set you are trying to evaluate it on.
- Do not reduce `MAX_KELLY_FRACTION` below 0.01 to "reduce exposure" — if the system is
  generating recommendations at all, staking nearly nothing makes the paper record
  statistically meaningless.

### Never

- Do not remove `PAPER_TRADE_ONLY=True` without completing the full live-readiness review.
- Do not change two parameters at the same time — you will not be able to attribute any
  observed change to either one.
- Do not change a parameter and then immediately compare last week's results to this week's
  results as validation — you need a new run of the backtest on historical data, not a
  week of live observation.

---

## 8. Current known parameter concerns (as of start of paper trading)

These are issues flagged during Phase 8 that are relevant to recommendation quality:

| Issue | Impact | Status |
|-------|--------|--------|
| `_load_best_model` selected the most-recent model, not the best Brier score | Recommendations could come from a suboptimal model | **RESOLVED.** It now builds the weighted ensemble from `Settings.ensemble_weights`, and falls back to the lowest-Brier compatible run. |
| Model class was always `BookmakerBaseline` regardless of what was trained | Recommendations were circular (odds compared back to themselves) | **RESOLVED.** Artifacts load per component, and a run whose stored `n_features` does not match the current schema is skipped rather than silently degraded. |
| TAB bookmaker availability in Odds API tier unconfirmed | Edge vs. TAB may be computed against a different bookmaker's line | Open — `TAB_BOOKMAKER_CONFIRMED` still gates live readiness. |

The circularity warning that stood here no longer applies: recommendations come
from trained models, not from the bookmaker's own implied probability. Edge
threshold and Kelly fraction can now be reasoned about on their merits — subject
to the evidence rules in the rest of this document.
