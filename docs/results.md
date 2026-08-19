# Evaluation results

**Verified run:** 2026-08-19 · Python 3.11.15 · scikit-learn 1.9.0 · XGBoost 3.2.0 ·
statsmodels 0.14.6 · pandas 2.3.3 · NumPy 2.4.6

Every number on this page was produced by the command in
[Reproducing this](#reproducing-this) on the date above. Nothing here is carried
over from an earlier benchmark. Historical figures that are *not* current are
kept separately in [`archive/ACCURACY_PLAN.md`](archive/ACCURACY_PLAN.md) and are
labelled there.

---

## Methodology

**Design:** expanding-window walk-forward. Fold *k* trains on every season
before season *k* and tests on season *k* only. Training data grows each fold;
test data is never seen during training.

| Setting | Value |
|---|---|
| Split mode | Expanding window (`backtesting/splits.py`) |
| Minimum training seasons | 2 |
| Season range | 2017–2025 |
| Test folds | 7 (2019, 2020, 2021, 2022, 2023, 2024, 2025) |
| Settled test matches | 1,413 |
| Data source | [Squiggle API](https://api.squiggle.com.au) — public, free, no key |
| Target | `home_win` ∈ {0, 1}. Draws excluded (`home_win = None`) |

**Why 2017–2025.** Bookmaker-consensus probabilities are available from 2017
onward at 100% coverage. 2015–2016 have none, and 2026 is in progress. Folds
without odds cannot produce a bookmaker baseline or any staking metric, and
averaging them together with covered folds would make the aggregate
incomparable. `--min-season 2017 --max-season 2025` excludes them explicitly
rather than silently.

### Leakage prevention

Temporal separation is enforced in code, not assumed:

- `backtesting/splits.py::_assert_no_leakage` (line 162) raises `LeakageError`
  unless `max(train.match_time) < min(test.match_time)`, and it runs on every
  fold as it is generated. (`check_temporal_order`, line 138, is a separate and
  weaker check: it warns if the frame is not sorted. The fold guard is the one
  that raises.)
- Elo ratings (`features/extractors/elo.py`) are the *pre-match* rating: a
  match's own result updates the rating only after that row is emitted.
- Form, rest, travel, venue and head-to-head windows read only matches with an
  earlier `match_time`.
- Bookmaker features require `snapshot_time < match_time`
  (`features/extractors/bookmaker.py`).
- Models are fitted only on settled training matches; the outcome column is
  dropped from every prediction input.

Both `tests/test_splits.py` and `tests/test_demo.py` assert the temporal
ordering rule directly.

### Hyperparameter independence

The tuners (`backtesting/elo_tuner.py`, `backtesting/xgb_tuner.py`) search over
the *same* walk-forward folds reported here. Any parameter they select is chosen
with knowledge of the test data, so publishing metrics produced with it would be
selection leakage.

**Every number on this page comes from `--untuned`**, which ignores
`storage/model_artifacts/*_best_params.json` and uses each model class's own
constructor defaults (`EloBaseline.__init__`, `XGBoostModel.__init__`). Nothing
tuner-derived enters the chain. Running without the flag logs a warning saying
the metrics are not publishable.

This required a correction. An earlier version of this page argued the point by
noting the metrics are unchanged when the parameter files are deleted. That proof
is circular: `run_backtest`'s fallback literals are **not** the model constructor
defaults (Elo defaults are k=30, home_advantage=60, season_regression=0.3; the
fallbacks are 24/50/0.70), and `git show 17b0e1b` puts those literals and the two
tuner artifacts in the same commit. Deleting the files therefore selected
duplicated tuner-era values, so byte identity proved only that two code paths
agreed with each other.

`--untuned` is the actual fix, and it moves the numbers: Elo's Brier goes from
0.2225 to 0.2246, XGBoost's from 0.2284 to 0.2269, the ensemble's from 0.2085 to
0.2081. The conclusion does not change — the market still wins every column, in
aggregate and in every season.

The parameter files carry no dataset or fold provenance. If you re-tune, use
nested walk-forward tuning, or freeze parameters on earlier seasons and keep the
reported folds untouched.

---

## Forecast quality

Lower Brier and log loss are better. Brier 0.25 is a coin flip.

| Model | Brier ↓ | Log loss ↓ | Accuracy ↑ | ECE ↓ |
|---|---|---|---|---|
| **Bookmaker consensus** (benchmark) | **0.1997** | **0.5811** | **68.6%** | **0.0678** |
| Logistic regression | 0.2056 | 0.5961 | 67.7% | 0.0871 |
| Ensemble (raw-component blend) | 0.2081 | 0.6033 | 67.4% | 0.0824 |
| Elo | 0.2246 | 0.6382 | 62.1% | 0.0762 |
| XGBoost | 0.2269 | 0.6649 | 65.8% | 0.1226 |
| Poisson (global baseline) | 0.2558 | 0.7104 | 56.8% | 0.0926 |

*n = 1,413 settled test matches across 7 folds. ECE = expected calibration error.*

### Per-season Brier score

| Season | n | Bookmaker | Logistic | Ensemble | Elo | XGBoost | Poisson |
|---|---|---|---|---|---|---|---|
| 2019 | 207 | **0.2139** | 0.2199 | 0.2316 | 0.2360 | 0.2876 | 0.2577 |
| 2020 | 160 | **0.1955** | 0.2158 | 0.2037 | 0.2348 | 0.2113 | 0.2538 |
| 2021 | 204 | **0.2183** | 0.2220 | 0.2255 | 0.2442 | 0.2456 | 0.2684 |
| 2022 | 206 | **0.1863** | 0.1880 | 0.1949 | 0.2233 | 0.2127 | 0.2413 |
| 2023 | 214 | **0.1982** | 0.2024 | 0.1991 | 0.2186 | 0.2031 | 0.2495 |
| 2024 | 209 | **0.2092** | 0.2155 | 0.2203 | 0.2151 | 0.2500 | 0.2576 |
| 2025 | 213 | **0.1763** | 0.1786 | 0.1815 | 0.2039 | 0.1765 | 0.2620 |

Bookmaker consensus has the lowest Brier score in all seven seasons.

2020 is the COVID season: 160 matches, shortened quarters, heavily disrupted
venues and travel. Treat it as an outlier rather than a data point.

---

## What these numbers actually say

**The market wins.** No model beats the bookmaker consensus on any of Brier, log
loss, accuracy, or calibration error, in aggregate or in any individual season.
The best model (logistic regression, 0.2056) sits about 3% worse than the
benchmark (0.1997).

That is the expected result, and reporting it plainly matters more than dressing
it up. AFL head-to-head markets are liquid and efficient; a consensus of
bookmakers prices them using strictly more information than this system has,
including team news that never reaches these features. A model that *did* beat
the closing consensus by a wide margin on 1,413 matches would be evidence of a
bug — most likely leakage — not of skill.

**The models that read the market land closest to it.** Logistic regression and
XGBoost consume `bm_home_implied_prob` directly, so they inherit most of the
market's information and add Elo and form on top; logistic lands just short of
the benchmark. Elo and Poisson do not see odds at all
(`models/elo_baseline.py`, `models/poisson_model.py`) and sit well behind.

This is a correlation across six models, not a measured effect. No no-odds
ablation was run, so the size of any "lift from odds" is not established here.

**The ensemble does not beat its best component.** Blending logistic (0.2056)
with three weaker models yields 0.2081 — worse than logistic alone, better than
everything else. Its ECE (0.0824) also sits between logistic's (0.0871) and
Elo's (0.0762), so the blend does not buy calibration either; what it buys is
variance reduction.

The row is labelled *raw-component* deliberately. It uses the production weights
from `Settings.ensemble_weights`, but not the production prediction function:
`generate_recommendations` wraps logistic and XGBoost in `CalibratedModel`
before blending, whereas the backtester fits them raw. Same blend, uncalibrated
components.

**So the shipped ensemble's calibration is not measured here, in either
direction.** Calibrating two of four components individually does not imply the
weighted blend has lower ECE — averaging calibrated with uncalibrated
probabilities can move calibration either way. A production-equivalent number
means running the calibration flow inside each fold, which this run does not do. It buys variance reduction and pays accuracy for it. Its ECE
(0.0782) is better than logistic's (0.0871), which is the defensible reason to
keep it: better-calibrated probabilities matter more than raw Brier for a
staking decision. The weights are configuration
(`Settings.ensemble_weights`), not a fitted result, and they have not been
optimised against this evaluation — deliberately, since tuning weights on the
same folds you report would invalidate the report.

**XGBoost underperforms logistic regression.** With ~1,600 training rows and 29
features, gradient boosting overfits where a linear model does not. Its ECE
(0.1175) is the worst in the table. This is a sample-size problem, not a
hyperparameter problem.

**Poisson is barely a model.** In score mode its GLM regresses on an intercept
and `is_final` only (`models/poisson_model.py::_fit_score_mode`) — no team
identity, no form, no market. Every regular-season match therefore receives the
*same* pair of scoring rates and the *same* win probability, which is why its
accuracy (56.8%) is identical to always picking the home team (56.8% on these
same matches). It is a global home-advantage baseline, not a match-specific
score-distribution model, and it should be read as a floor rather than a
competitor. The machinery to condition it on team attack/defence exists in the
class but is not wired to features.

---

## Simulated staking (weak evidence — read the caveats)

The backtester also simulates paper bets: edge = model probability − implied
probability, staked at capped Kelly when edge > 3%.

| Model | Bets | Hit rate* | Avg edge* | ROI |
|---|---|---|---|---|
| Elo | 1,229 | 41.0% | 0.149 | +0.6% |
| XGBoost | 1,216 | 54.9% | 0.153 | +0.4% |
| Poisson | 1,299 | 35.9% | 0.211 | −0.4% |
| Ensemble | 1,095 | 37.2% | 0.097 | −3.9% |
| Logistic | 931 | 46.5% | 0.074 | −6.7% |
| Bookmaker | 0 | — | — | — |

\* Hit rate and average edge are unweighted means across the 7 folds
(`backtesting/metrics.py::_bet_avg`), not pooled rates over all listed bets, so
they do not equal wins ÷ bets. A small fold counts as much as a large one. ROI
*is* pooled (total profit ÷ total staked). The aggregate output does not retain
per-fold win counts, so the pooled hit rate cannot be recovered from the
artifact.

**Do not read these as expected returns.** Three reasons, in order of severity:

1. **The prices carry no bookmaker margin.** The consensus feed yields implied
   probabilities that sum to exactly 1.0 (`bm_overround = 1.0`). Real
   Australian H2H markets run at roughly 105–110% overround. Betting into
   margin-free prices is not achievable, and it inflates every ROI figure here.
2. **The "edges" are concentrated on longshots.** All models regress strong
   favourites toward the mean, so they look most confident *relative to the
   market* on outsiders. Most recommendations are longshot bets where the model
   is simply less certain than the market — which is a calibration weakness
   being mistaken for an edge, not an edge. The ROI ordering is the inverse of
   the forecast-quality ordering, which is exactly what you would expect from
   variance rather than skill.
3. **The sample is too small and too correlated.** ~1,200 simulated bets over
   seven seasons, many on the same teams in the same seasons. Bootstrap
   confidence intervals (`backtesting/bootstrap.py`) were not computed for this
   run; without them these point estimates carry no significance claim.

**No CLV figures are reported.** Closing-line value requires a real opening
price and a real closing price per market. The historical consensus feed
provides a single figure per match, so CLV cannot be computed on this dataset.
`evaluation/clv_tracker.py` computes it from live-captured snapshots during
paper trading; the accumulated paper-trading sample is not yet large enough to
report.

---

## Data caveats

| Caveat | Detail |
|---|---|
| Odds are a consensus, not a book | Squiggle's Punters feed (`source=5`) gives one market-consensus implied probability per match, not a specific bookmaker's price. |
| Odds source was audited, not assumed | `backfill_squiggle_odds.py` falls back to Squiggle's own *model* (`source=1`) when no Punters consensus exists — a model estimate, not a market price. Re-querying the API for 2017–2025 found **0 fallbacks out of 1,845 games**, so every record behind these results is genuine Punters consensus. The loader now tags any fallback `snapshot_type='historical_model_estimate'` and warns, so this is checkable rather than hand-audited next time. |
| Odds have a synthetic timestamp | The feed carries no capture time. `backfill_squiggle_odds.py` stamps each snapshot 2 hours pre-match so it satisfies the `snapshot_time < match_time` rule. The true capture time is unknown and probably closer to kickoff, which makes the benchmark *stronger* than a genuine morning line. |
| Zero overround | See caveat 1 under staking. |
| No weather | No historical weather was collected for these seasons. Weather features exist in the schema and are null throughout. Their contribution to these results is exactly zero. |
| Poisson is a global baseline | Its GLM sees only an intercept and `is_final`, so every regular-season match gets the same probability. See the discussion above. |
| Player availability carries no signal at all | Not merely approximate: `collectors/player_collector.py` hard-codes every historical lineup to availability `1.0` with zero absences, and the extractor returns the same values when data is missing. All 1,413 evaluation rows are identical, so these features contribute exactly nothing to the results. The described expected-vs-available algorithm is not implemented. |
| Draws excluded | AFL draws are rare (~0.5%) and dropped rather than modelled as a third class. |
| Models here are uncalibrated | The backtester fits raw models. Production additionally wraps logistic and XGBoost in isotonic calibration (`models/calibrated_model.py`, applied by `train_models.py`), which is not reflected in this table. |

---

## Reproducing this

Requires network access to the Squiggle API (free, no key). Roughly 5 minutes.

```bash
# 1. Fixtures and results, 2017 onward
for y in 2017 2018 2019 2020 2021 2022 2023 2024 2025; do
  python -m orchestration.jobs.ingest_afl --season $y
done

# 2. Historical market-consensus probabilities
python -m orchestration.jobs.backfill_squiggle_odds

# 3. Feature matrix
python -m orchestration.jobs.build_features

# 4. Walk-forward backtest over the odds-covered seasons.
#    --untuned is not optional for publishable numbers — see "Hyperparameter
#    independence" above. Without it, the job loads tuner output selected on
#    these same folds and logs a warning saying so.
python -m orchestration.jobs.run_backtest --min-season 2017 --max-season 2025 --untuned
```

The result artifact lands in `storage/raw_snapshots/backtest_results/` as JSON
with per-fold and aggregate metrics. That directory is gitignored, so the exact
artifact behind this page is committed separately as
[`../examples/backtest_2026-08-19.json`](../examples/backtest_2026-08-19.json) —
every table above is transcribed from it and can be checked against it.

Numbers are deterministic given the same data: models are seeded
(`random_state=42`), splits are by calendar season, and no sampling is involved.

They are **not** reproducible from committed inputs alone. The feature parquet is
gitignored, step 1–3 depend on live Squiggle data that may be retroactively
corrected, and `requirements.txt` pins version ranges rather than exact versions,
so a scikit-learn or XGBoost minor release can shift the numbers. The committed
artifact is inspectable and the tables above are checkable against it; exact
recomputation from a clean clone is not guaranteed. Pinning a lockfile and
committing the parquet would fix that and has not been done.

For a fast, network-free taste of the pipeline on one held-out round, run
`make demo` — but note that ten matches cannot evaluate a model. This page can.
