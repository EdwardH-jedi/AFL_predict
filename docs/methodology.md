# Methodology

How predictions are produced and, more importantly, how they are kept honest.

---

## 1. The one invariant

**No feature value may depend on information that did not exist before the match
started.**

Everything below follows from that. In a sports-forecasting codebase, leakage is
not a rare bug — it is the default failure mode, because the obvious way to
compute "team form" is to group by team and average, which quietly includes the
match being predicted.

Three layers enforce it:

1. **Extractor design.** Every extractor filters to matches with an earlier
   `match_time` before computing anything.
2. **Split assertions.** `backtesting/splits.py::check_temporal_order` raises
   `LeakageError` unless `max(train.match_time) < min(test.match_time)` for
   every fold. It is an assertion, not a warning.
3. **Tests.** `tests/test_splits.py` asserts the ordering rule and that the
   guard actually fires on a violation; `tests/test_elo_extractor.py` and
   `tests/test_form_extractor.py` assert that a match's own result does not
   appear in its own features.

---

## 2. Features

`features/feature_builder.py` runs each extractor and joins the results into one
row per match. Extractors are independent — adding one cannot change another's
output.

| Extractor | Produces | Pre-match guarantee |
|---|---|---|
| `elo.py` | `home_elo_pre`, `away_elo_pre`, `elo_diff` | Ratings are emitted *before* the match updates them. Iterating chronologically, the row is written and only then is the rating adjusted. |
| `form.py` | Win rates over L3/L5/L10, points for/against, momentum | Rolling windows over strictly earlier matches. Momentum = short-window minus long-window form. |
| `h2h.py` | `h2h_home_win_rate_l5`, `h2h_avg_margin_l5`, `h2h_games_played` | Prior meetings of the same two clubs only. |
| `venue.py`, `venue_performance.py` | Per-team venue win rate, venue home advantage, `is_neutral_venue` | Earlier matches at that venue only. |
| `rest.py` | `home_rest_days`, `away_rest_days` | Days since each side's previous match. |
| `travel.py` | Interstate flags, `travel_km`, `travel_km_diff` | Geographic; time-invariant. |
| `bookmaker.py` | `bm_home_odds`, `bm_*_implied_prob`, `bm_overround` | Requires `snapshot_time < match_time`. Enforced in the query, not the caller. |
| `odds_movement.py` | Opening odds, drift, `bm_line_move` | Compares two pre-match snapshots. |
| `weather.py` | Temperature, wind, rain flags, `weather_scoring_index` | Forecast for the venue, captured pre-match. |
| `player_availability.py` | Availability index, key absences | Derived from prior-season participation, not confirmed team sheets. Approximate — see caveats in [`results.md`](results.md). |

The logistic and XGBoost models consume 29 of these columns
(`models/logistic_baseline.py::FEATURE_COLS`). Elo uses only ratings; the
bookmaker baseline uses only implied probability; Poisson uses scoring rates.

**Target:** `home_win ∈ {0, 1}`. Draws (~0.5% of AFL matches) are stored as
`None` and excluded rather than modelled as a third class.

---

## 3. Models

Five forecasters plus a blend. All implement `BaseModel`, so every consumer is
model-agnostic.

### Bookmaker baseline — the benchmark

Converts market implied probability directly into a forecast, de-vigged. This is
the number to beat, and it is deliberately **not** a component of the production
ensemble: blending the market into the model shrinks predictions toward the
market and suppresses the very disagreement the recommendation step looks for.
`Settings.ensemble_weight_bookmaker_baseline` defaults to `0.0` for that reason.

### Elo

Standard Elo on match outcomes with a home-ground bonus and between-season
regression toward the mean. Stateless at inference: no artifact, just ratings
carried forward. Tuned offline by `backtesting/elo_tuner.py` (k-factor, home
advantage, season regression) into `storage/model_artifacts/elo_best_params.json`.

Elo is the low-variance member of the ensemble. It is weak alone but it does not
lurch, which is what makes it useful in a blend.

### Logistic regression

L2-regularised logistic regression over the 29 features, standardised. Rows with
NaN in a selected feature are dropped rather than imputed, so a missing odds
snapshot cannot become a fabricated 0.5.

Linear, and on this dataset that is a feature. With ~1,600 training rows it
generalises better than gradient boosting — see [`results.md`](results.md).

### XGBoost

Gradient-boosted trees over the same features, with early stopping and SHAP
importances available. Auto-detects CUDA. Overfits on this sample size; kept
because it contributes something different to the blend, not because it wins.

### Poisson

Models home and away scoring rates as Poisson processes (statsmodels GLM), then
integrates the score-difference distribution to a win probability.

**In its current wiring this is a global baseline, not a match-specific model.**
`_fit_score_mode` regresses score on an intercept and `is_final` only — no team
identity, no form, no market. So every regular-season match receives the same
pair of scoring rates and the same win probability, and its accuracy comes out
identical to always picking the home team. The class supports conditioning on
richer covariates; nothing currently supplies them. Read its row in
[`results.md`](results.md) as a floor, and do not read the ensemble's Poisson
component as contributing match-level information.

### Calibration

A model can rank matches well and still state the wrong probability. Since
stake size is a function of the *probability*, not the ranking, calibration is
load-bearing here rather than cosmetic.

`CalibratedModel` wraps logistic and XGBoost with post-hoc isotonic regression,
fitted **out of sample**:

```text
seasons 1 .. N-2   fit the base model
season  N-1        fit the isotonic calibrator on the base model's predictions
season  N          evaluate
```

The base model is **not** refit on seasons 1..N-1 afterwards. An isotonic
calibrator is tied to the output distribution of one specific fitted model;
refitting the base shifts that distribution and leaves the calibrator mapping
stale probabilities. That was measured, not assumed — ECE ballooned to 0.31
under the refit flow. The cost is one season less training data for the base
model. The benefit is probabilities that mean what they say.

Quality is reported as **ECE** (expected calibration error) alongside Brier and
log loss, with reliability bins in `backtesting/calibration.py`.

### Ensemble

Weighted average of component probabilities, renormalised.

Weights live in exactly one place: `Settings.ensemble_weights`
(`config/settings.py`), keyed by the persisted `ModelRun.model_name`. Defaults:

| Component | Weight |
|---|---|
| `logistic_baseline` | 0.30 |
| `xgboost` | 0.35 |
| `poisson` | 0.20 |
| `elo_baseline` | 0.15 |
| `bookmaker_baseline` | 0.00 (excluded — it is the benchmark) |

Two properties worth noting:

- **Degradation, not failure.** A component whose artifact is missing, stale, or
  broken is dropped and the remaining weights renormalise. Fewer than two
  components available → the job falls back to the single best model by Brier.
- **Stale-artifact rejection.** Each candidate `ModelRun`'s stored `n_features`
  must match the current feature schema. A model trained on an older feature set
  is skipped rather than loaded against mismatched columns.

Weights are configuration, not a fitted result. `models/ensemble.py::optimize_weights`
can search them against a validation set, but the production blend is not tuned
against the evaluation folds reported in [`results.md`](results.md) — doing so
would make that report meaningless.

---

## 4. Validation

### Walk-forward, expanding window

```text
fold 1   train 2017-2018        test 2019
fold 2   train 2017-2019        test 2020
fold 3   train 2017-2020        test 2021
...
fold 7   train 2017-2024        test 2025
```

Training data grows; test data is always strictly in the future. Rolling-window
mode (fixed-size training window) is also available via `--mode rolling`.

Why not k-fold cross-validation: random folds put future matches in the training
set for past matches. On time-series data that inflates every metric and the
inflation is invisible, because nothing errors.

### Metrics

| Metric | Measures | Reference |
|---|---|---|
| **Brier score** ↓ | Mean squared probability error | 0.25 = coin flip |
| **Log loss** ↓ | Penalises confident errors severely | 0.693 = coin flip |
| **Accuracy** ↑ | Fraction of correct picks at p = 0.5 | ~57% = always pick home |
| **ECE** ↓ | Gap between stated and observed frequency | 0 = perfect |

Brier and log loss lead because the system's output is a probability that sizes
a stake, not a binary pick. Accuracy is the weakest of the four: a model can be
69% accurate while being badly calibrated, and badly calibrated probabilities
destroy a Kelly-sized bankroll.

### Staking simulation

Per fold the backtester also computes what a paper bettor would have done:

```text
edge  = model_prob - implied_prob
if edge > edge_threshold (default 0.03):
    kelly = (model_prob * (odds - 1) - (1 - model_prob)) / (odds - 1)
    stake = min(kelly, max_kelly_fraction)      # default cap 0.05
```

One bet per match, on the higher-edge side. Full Kelly hard-capped at 5% of
bankroll — Kelly is optimal only if the probability is exactly right, which it
never is, so the cap is doing real work.

`backtesting/bootstrap.py` resamples bet sequences for confidence intervals on
ROI, hit rate and Sharpe. **Point estimates without intervals are not evidence**,
and the staking figures in [`results.md`](results.md) are labelled accordingly.

---

## 5. What this methodology cannot tell you

- **Simulated ROI is not expected return.** The historical consensus prices carry
  no bookmaker margin (overround = 1.0). Real markets take 5–10%. Every
  simulated ROI is optimistic by roughly that much.
- **A held-out round proves nothing.** `make demo` scores ten matches. Ten
  matches cannot separate a good model from a lucky one.
- **CLV needs live capture.** Closing-line value requires a real opening and
  closing price per market. The historical feed has one figure per match, so CLV
  is only computable on prices captured live during paper trading.
- **Beating the market by a lot would be a bug.** On 1,413 matches, a large edge
  over a bookmaker consensus is more likely leakage than skill. The measured
  result — slightly *worse* than the market — is the credible one.

---

See [`results.md`](results.md) for the verified numbers,
[`backtesting.md`](backtesting.md) for runner internals, and
[`features.md`](features.md) for the extractor-by-extractor reference.
