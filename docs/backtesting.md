# Backtesting — Methodology, Leakage Policy, and Result Interpretation

## Purpose

The backtest pipeline provides out-of-sample evaluation of baseline prediction
models against historical AFL head-to-head results. Its primary goals are:

1. **Verify that models contain real predictive information** — better than a
   naive baseline (coin-flip Brier = 0.25, bookmaker-implied probability).
2. **Measure calibration** — predicted probabilities should match empirical
   win rates.
3. **Simulate paper-trade profitability** — would betting the model's edge
   against the bookmaker have been profitable? (Not a guarantee of future results.)
4. **Prevent false confidence** — a backtest is easier to make look good than
   it is to make profitable live. All results should be interpreted conservatively.

> **Important:** A positive backtest ROI does not imply future profitability.
> AFL markets are efficient. Any apparent edge may be due to small sample size,
> overfitting, or survivorship bias in the features.

---

## Leakage Policy

**No information about a match's outcome may appear in any feature used to
predict that match.**

### Enforced at every layer

| Layer                   | Leakage prevention                                                    |
|-------------------------|-----------------------------------------------------------------------|
| EloExtractor            | Pre-match ELO uses only results with `match_time < current match`     |
| FormExtractor           | Rolling form uses only completed games before the current match       |
| BookmakerExtractor      | Only `snapshot_time < match_time` odds snapshots are used             |
| RestDaysExtractor       | Uses `match_time` only (no result information)                        |
| Temporal split          | Training data: all seasons before the test season                     |
| Split assertion         | `max(train.match_time) < min(test.match_time)` — raises `LeakageError` on violation |

### What leakage looks like (and why it matters)

If you accidentally include any of the following in training features, results
will be artifically optimistic:

- Final scores (`home_score`, `away_score`) — these are only known after the match
- `result` or `home_win` on the same row being predicted
- ELO ratings computed using the current match's result
- Bookmaker closing odds captured after the game started
- Form statistics that include the match being predicted

The `features/validators.py` leakage checks will log `ERROR`-level messages
if violations are detected during `build_features`. Any non-zero leakage count
must be investigated and fixed before trusting results.

---

## Split Strategy

### Expanding-window (recommended)

```
Seasons:  [2019, 2020, 2021, 2022, 2023, 2024]

Fold 0:   train=[2019, 2020],       test=[2021]
Fold 1:   train=[2019, 2020, 2021], test=[2022]
Fold 2:   train=[2019..2022],       test=[2023]
Fold 3:   train=[2019..2023],       test=[2024]
```

Training data grows with each fold, using all available history. This is the
most data-efficient strategy and mirrors how a model would actually be updated
between seasons.

### Rolling-window (optional)

```
Fold 0:   train=[2019, 2020, 2021], test=[2022]
Fold 1:   train=[2020, 2021, 2022], test=[2023]
Fold 2:   train=[2021, 2022, 2023], test=[2024]
```

Fixed training window. Useful for checking whether older data hurts or helps.
Run with `--mode rolling --min-train-seasons 3`.

### Why not random splits?

AFL matches are a time series. Using a random 80/20 split would:
- Allow the model to train on future results and predict past ones (leakage).
- Overestimate out-of-sample performance by an unknown (and likely large) margin.
- Make results incomparable to live deployment, which always predicts the future.

---

## Baseline Models

### BookmakerBaseline

Uses the bookmaker's own implied probability (after overround removal) as the
prediction. This is the **performance ceiling** — a model that cannot beat this
on out-of-sample Brier score or log loss is not worth using.

Expected metrics: best Brier score, best log loss. If another model beats this,
check for data leakage first.

*These are design expectations, not results. The measured outcome — the benchmark
does win Brier and log loss in aggregate and in every test season — is in
[`RESULTS.md`](RESULTS.md) §8.*

### EloBaseline

Maintains team ELO ratings updated match-by-match from historical results.
Win probability is derived from the rating difference using the standard ELO
formula with home advantage offset.

Expected metrics: better than coin-flip but worse than bookmaker. Captures
long-run team strength but ignores recent form and market information.

Parameters (in `models/elo_baseline.py`):
- K-factor: 30 (update rate)
- Home advantage: +60 ELO points
- Season regression: 30% toward current-season mean

### LogisticBaseline

Scikit-learn logistic regression trained on all available pre-match features:
bookmaker implied probs, ELO ratings, rolling form, rest days, is_final.

Expected metrics: may slightly improve on EloBaseline by combining multiple
signals. Should not significantly beat BookmakerBaseline on calibration.

---

## Metrics Reference

### Probability quality

| Metric       | Interpretation                                                  |
|--------------|------------------------------------------------------------------|
| Brier score  | Mean squared error between predicted prob and outcome. Lower = better. Coin-flip baseline = 0.25. |
| Log loss     | Penalises confident wrong predictions heavily. Lower = better.  |
| Accuracy     | Fraction of matches where predicted favourite (prob > 0.5) won. Baseline ≈ 0.57 (home team wins more). |
| ECE          | Expected calibration error. Lower = better. < 0.05 is well-calibrated. |

### Decision quality

| Metric        | Interpretation                                                           |
|---------------|---------------------------------------------------------------------------|
| n_bets        | Matches where model edge ≥ threshold. More bets = more exposure.         |
| n_no_bet      | Matches below threshold — model abstained.                               |
| hit_rate      | Fraction of recommended bets that won. > 0.5 is required for positive ROI at typical odds. |
| avg_edge      | Mean (model_prob − bm_implied_prob) for placed bets. Higher = more confident edge. |
| total_staked  | Sum of Kelly fractions (virtual unit). Measure of total exposure.        |
| ROI           | (Profit − Staked) / Staked. **Positive ROI does not imply future profitability.** |

### Calibration bins

The calibration report groups predicted probabilities into 10 equal-width bins
and reports the empirical win rate for each. A perfectly calibrated model has
`actual_fraction ≈ mean_predicted` in every bin.

Illustrative example of well-calibrated output (synthetic — not a measured
result; for measured calibration see [`RESULTS.md`](RESULTS.md) §9):
```
[0.40,0.50)  mean_pred=0.4530  actual=0.4480  gap=-0.0050   count=  82
[0.50,0.60)  mean_pred=0.5490  actual=0.5510  gap=+0.0020   count=  94
[0.60,0.70)  mean_pred=0.6380  actual=0.6250  gap=-0.0130   count=  48
```

---

## Recommendation Simulation

The simulation models the same decision rule as `generate_recommendations.py`:

1. Compute `edge = model_prob − bm_implied_prob` for home and away sides.
2. If `max(home_edge, away_edge) ≥ edge_threshold`: recommend the higher-edge side.
3. `stake_fraction = min(kelly_fraction, max_kelly_fraction)`.
4. If neither side clears the threshold: no-bet.

The simulation is **purely in-memory** — no database writes occur. Results are
attached to the `BacktestResult` artifact.

**Assumptions baked into the simulation:**
- Odds are fixed at the pre-match snapshot (no closing-line movement modelled).
- One bet per match at most.
- Full Kelly criterion (not fractional Kelly) is used before the cap.
- No account restrictions, minimum bets, or queue effects are modelled.

---

## Interpreting Results

### What good results look like

- `brier_score` < 0.24 (beating coin-flip meaningfully)
- `ece` < 0.05 (well-calibrated)
- `accuracy` > 0.58 (above naive home-team-always baseline)
- `hit_rate` > 0.52 (winning more than half of recommended bets)
- `roi` near 0 or slightly positive (not negative, which would be -EV)

### Warning signs

- Model `brier_score` ≈ BookmakerBaseline: the model adds no value over market.
- Model `brier_score` significantly *better* than BookmakerBaseline: suspect leakage.
- `hit_rate` < 0.45: model is systematically wrong — check features.
- `n_bets` is very low (< 5 per season): edge threshold too high, or model rarely disagrees with market.
- `roi` > 0.05 on backtest: almost certainly overfitting on a small sample.

### Sample size caution

An AFL season contains ~207 matches. Excluding draws (~4%), that is ~198 binary
outcomes. A single season's backtest has very wide confidence intervals:

- 95% CI on hit_rate of 0.55 from 50 bets: approximately ±0.14.
- Minimum ~5 seasons of data before backtest metrics are meaningful.

---

## Local Run Instructions

### Full backtest (all models, all seasons)

```bash
make build-features
make backtest
```

### Rolling window

```bash
make backtest ARGS="--mode rolling --min-train-seasons 3"
```

### Higher edge threshold

```bash
make backtest ARGS="--edge-threshold 0.05"
```

### Train single model for deployment

```bash
make train-models
```

### Example output

The shape of a run. **These figures are illustrative, not measured** — they come
from an early 3-fold configuration and do not match the current evaluation. For
the canonical numbers see [`RESULTS.md`](RESULTS.md).

```
==> run_backtest: starting (mode=expanding, min_train_seasons=2, edge_threshold=0.03)
BacktestRunner: starting expanding-window backtest
BacktestRunner: fold 1/7 — 2019 (train=411, test=207)
[bookmaker_baseline] fold=2019 brier=... ll=... acc=... bets=0 roi=nan
...
BacktestResult saved to storage/raw_snapshots/backtest_results/backtest_<id>_<ts>.json

           model_name  n_folds  n_settled_total  brier_score  ...  roi
   bookmaker_baseline        7             1413       0.199678  ...  NaN
    logistic_baseline        7             1413       0.205576  ... -0.067
```

Note that `bookmaker_baseline` records **zero bets and a null ROI** by
construction: edge is model probability minus market implied probability, and for
this model those are the same number, so no selection can clear the threshold.

---

## Outstanding TODOs

```
TODO: backtesting/runner.py — Add support for multi-season test windows
      (currently test_seasons=1 is hardcoded in split calls).

TODO: models/elo_baseline.py — Tune K-factor and home_advantage on held-out
      validation data once 3+ seasons of results are available.

TODO: backtesting/simulation.py — Model closing-line movement: use the
      latest available odds snapshot rather than fixed opening odds.

TODO: backtesting — Add significance testing (permutation test or bootstrap
      CI) around Brier score differences between models.

TODO: backtesting — Store calibration bin data in BacktestResult artifact
      so calibration plots can be reproduced from the JSON file.
```
