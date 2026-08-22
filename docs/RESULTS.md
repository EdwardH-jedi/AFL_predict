# Results

**Last verified:** 2026-08-21
**Evaluation run:** 2026-08-19T08:28:38Z
**Documented at commit:** `a700ecd`
**Canonical artifact:** [`../examples/backtest_2026-08-19.json`](../examples/backtest_2026-08-19.json)

Every current result on this page is transcribed from that artifact and can be
checked against it. The only other figures quoted are three superseded tuned-era
Brier values in [§7](#7-tuned-vs-untuned), each labelled as such and used only to
show the size of a correction.

---

## 1. Evaluation objective

The system is evaluated on **pre-match win-probability quality for AFL
head-to-head outcomes**, against the bookmaker consensus as the benchmark.

Four dimensions are implemented and reported:

| Dimension | Implemented in | Reported |
|---|---|---|
| Probabilistic accuracy | `backtesting/metrics.py` | Brier, log loss |
| Classification accuracy | `backtesting/metrics.py` | Accuracy at p = 0.5 |
| Calibration | `backtesting/calibration.py` | ECE, reliability bins |
| Decision value (paper) | `backtesting/simulation.py` | Bets, hit rate, edge, ROI |

Ranking metrics (ROC-AUC) are **not** implemented and are not reported.

---

## 2. Evaluation dataset

| Property | Value |
|---|---|
| Source | [Squiggle API](https://api.squiggle.com.au) — public, free, no key |
| Seasons in scope | 2017–2025 |
| Test folds | 7 (2019, 2020, 2021, 2022, 2023, 2024, 2025) |
| Settled test matches | 1,413 |
| Split mode | Expanding-window walk-forward (`backtesting/splits.py`) |
| Minimum training seasons | 2 |
| Target | `home_win ∈ {0, 1}` |

**Exclusions.** Draws (~0.5% of AFL matches) are stored as `None` and excluded
rather than modelled as a third class. Seasons 2015–2016 are excluded because
they have no bookmaker-odds coverage; 2026 is excluded as in progress. Folds
without odds cannot produce a bookmaker baseline or any staking metric, and
averaging them with covered folds would make the aggregate incomparable, so
`--min-season 2017 --max-season 2025` excludes them explicitly.

### Temporal leakage risk — investigated

Enforced in code, not asserted in prose:

- `backtesting/splits.py::_assert_no_leakage` raises `LeakageError` unless
  `max(train.match_time) < min(test.match_time)`, and runs on every fold as it is
  built. (`check_temporal_order` is a separate, weaker sortedness check that only
  logs a warning — it is not the guard.)
- Elo (`features/extractors/elo.py`) emits the *pre-match* rating: a match's own
  result updates the rating only after that row is written.
- Form, head-to-head, venue-performance and rest extractors iterate
  chronologically and emit a row *before* that match updates their state; travel
  and venue are stateless (geography and fixture metadata). The protection is
  emit-before-update ordering, not a per-query timestamp filter — both are sound,
  but they are different mechanisms and only the fold guard is universal.
- Bookmaker features require `snapshot_time < match_time`
  (`features/extractors/bookmaker.py`).
- Models fit only on settled training matches; the outcome column is dropped from
  every prediction input.

Direct extractor-level leakage tests exist for Elo, form and bookmaker
(`tests/test_elo_extractor.py`, `test_form_extractor.py`,
`test_bookmaker_extractor.py`); the fold-level guard is covered by
`tests/test_splits.py` and `tests/test_demo.py`. The remaining extractors
(h2h, venue, venue-performance, rest, travel, weather, odds-movement,
player-availability) are **not** individually leakage-tested — a real coverage
gap, listed in `PROJECT_STATUS.md` §11.

Two weaker spots found while auditing: the weather extractor joins on `match_id`
without asserting `fetched_at < match_time`, and player records can be accepted
with a null announcement timestamp. Neither affects the reported results, because
both feature families are constant across this dataset (§14).

Two leakage vectors that are **not** structural but were checked explicitly:
hyperparameter selection (§7) and odds provenance (§4).

---

## 3. Models evaluated

| Model | Role | Tuned? | Notes |
|---|---|---|---|
| `bookmaker_baseline` | Benchmark | n/a | Market implied probability. Stateless. Excluded from the production ensemble by design. |
| `elo_baseline` | Component | **No** — constructor defaults (k=30, home adv=60, season regression=0.3) | Stateless at inference. |
| `logistic_baseline` | Component | No | L2 logistic over 29 features; median imputation + standardisation in a fitted `Pipeline`. |
| `xgboost` | Component | **No** — constructor defaults (depth 4, lr 0.05, 300 est.) | `random_state=42`. CPU-only as wired. |
| `poisson` | Component | No | See §11 — a global baseline in its current wiring, not a match-specific model. |
| `ensemble` | Blend | No | Weighted average from `Settings.ensemble_weights`; raw (uncalibrated) components in this run. |

Verified from `orchestration/jobs/run_backtest.py` and `models/*.py`.

---

## 4. Bookmaker baseline

**Derivation.** `models/bookmaker_baseline.py` returns
`bm_home_implied_prob` / `bm_away_implied_prob` directly as the forecast. No
fitting occurs. Rows with missing odds fall back to 0.5/0.5, which does not arise
in this evaluation because odds coverage is 100% across 2017–2025.

**Source and margin.** Probabilities come from Squiggle's Punters feed
(`sourceid=5`), a bookmaker-consensus implied probability per match, backfilled by
`orchestration/jobs/backfill_squiggle_odds.py`. The feed is **already
overround-normalised**: home + away = 1.0 exactly (`bm_overround = 1.0`). No
de-vigging step is applied because none is needed — and this is the single most
important caveat on §10.

**Provenance, audited not assumed.** The loader falls back to Squiggle's own
*model* (`sourceid=1`) when no consensus exists — a model estimate, not a market
price, which would make the benchmark partly a model-vs-model comparison.
Re-querying the API across 2017–2025 found **0 fallbacks in 1,845 games**, so
every record behind these results is genuine consensus. Fallback rows are now
tagged `snapshot_type='historical_model'` and warned about, so this is checkable
rather than hand-audited next time.

**Timestamp is synthetic.** The feed carries no capture time. The loader stamps
each snapshot two hours pre-match so it satisfies the `snapshot_time <
match_time` rule. The true capture time is unknown and probably closer to
kickoff, which makes this benchmark *stronger* than a genuine morning line.

**What this supports.** A like-for-like comparison of probability quality against
a margin-free market consensus. It does **not** support any claim about beating a
real, priced bookmaker market, because no real market is margin-free.

---

## 5. Metrics

| Metric | Direction | Meaning | Reference point |
|---|---|---|---|
| Brier score | lower better | Mean squared probability error | 0.25 = coin flip |
| Log loss | lower better | Penalises confident errors severely | 0.693 = coin flip |
| Accuracy | higher better | Correct picks at p = 0.5 | 56.8% = always pick home |
| ECE | lower better | Gap between stated and observed frequency | 0 = perfect |
| ROI | higher better | (profit − staked) / staked, simulated | see §10 caveats |

Brier and log loss lead because the system's output is a probability that sizes a
stake, not a binary pick. Accuracy is the weakest of the four: a model can be 69%
accurate while badly calibrated, and badly calibrated probabilities are what
destroy a Kelly-sized bankroll.

---

## 6. Main results

**Command** (the exact form behind every number below):

```bash
python -m orchestration.jobs.run_backtest --min-season 2017 --max-season 2025 --untuned
```

| Model | Brier ↓ | Log loss ↓ | Accuracy ↑ | ECE ↓ |
|---|---|---|---|---|
| **Bookmaker consensus** (benchmark) | **0.1997** | **0.5811** | **68.6%** | **0.0678** |
| Logistic regression | 0.2056 | 0.5961 | 67.7% | 0.0871 |
| Ensemble (raw-component blend) | 0.2081 | 0.6033 | 67.4% | 0.0824 |
| Elo | 0.2246 | 0.6382 | 62.1% | 0.0762 |
| XGBoost | 0.2269 | 0.6649 | 65.8% | 0.1226 |
| Poisson (global baseline) | 0.2558 | 0.7104 | 56.8% | 0.0926 |

*n = 1,413 settled test matches across 7 folds.*

---

## 7. Season-level results

Brier score per test season:

| Season | n | Bookmaker | Logistic | Ensemble | Elo | XGBoost | Poisson |
|---|---|---|---|---|---|---|---|
| 2019 | 207 | **0.2139** | 0.2199 | 0.2316 | 0.2360 | 0.2876 | 0.2577 |
| 2020 | 160 | **0.1955** | 0.2158 | 0.2037 | 0.2348 | 0.2113 | 0.2538 |
| 2021 | 204 | **0.2183** | 0.2220 | 0.2255 | 0.2442 | 0.2456 | 0.2684 |
| 2022 | 206 | **0.1863** | 0.1880 | 0.1949 | 0.2233 | 0.2127 | 0.2413 |
| 2023 | 214 | **0.1982** | 0.2024 | 0.1991 | 0.2186 | 0.2031 | 0.2495 |
| 2024 | 209 | **0.2092** | 0.2155 | 0.2203 | 0.2151 | 0.2500 | 0.2576 |
| 2025 | 213 | **0.1763** | 0.1786 | 0.1815 | 0.2039 | 0.1765 | 0.2620 |

2020 is the COVID season: 160 matches, shortened quarters, disrupted venues and
travel. Treat it as an outlier rather than a data point.

### Tuned vs untuned

The tuners (`backtesting/elo_tuner.py`, `backtesting/xgb_tuner.py`) search over
the *same* walk-forward folds reported here. Any parameter they select is chosen
with knowledge of the test data, so publishing metrics produced with it would be
selection leakage.

**Canonical results are `--untuned`**: `run_backtest --untuned` ignores
`storage/model_artifacts/*_best_params.json` and uses each model class's own
constructor defaults, inside `_build_ensemble` as well as for the standalone
rows. Running without the flag logs a warning that the metrics are not
publishable. Tuned and untuned numbers are never mixed in a table on this page.

This required a correction worth recording. An earlier version argued
independence from the fact that metrics are unchanged when the parameter files
are deleted. That proof is circular: `run_backtest`'s fallback literals are not
the model constructor defaults (Elo defaults are 30/60/0.3; the fallbacks were
24/50/0.70), and `git show 17b0e1b` puts those literals and the tuner artifacts in
the same commit. Deleting the files selected duplicated tuner-era values, so byte
identity proved only that two code paths agreed with each other.

`--untuned` moved the numbers: Elo 0.2225 → 0.2246, XGBoost 0.2284 → 0.2269,
ensemble 0.2085 → 0.2081. *(Those three are the superseded tuned-era values.)*
The conclusion did not change.

---

## 8. Bookmaker comparison

Stated precisely, because the distinction matters:

> **The models do not beat the bookmaker consensus.**
> The benchmark wins **all four metrics in aggregate**, and wins **Brier and log
> loss in every one of the seven test seasons**.

Where individual models do edge ahead, in single seasons only:

| Metric | Seasons the benchmark loses | Best case |
|---|---|---|
| Accuracy | 2020, 2023, 2024, 2025 | XGBoost 75.1% vs 73.7% (2025); largest margin logistic +2.8pp (2023) |
| ECE | 2020, 2022, 2023, 2024 | Elo repeatedly (e.g. 0.0522 vs 0.0932 in 2024) |

These are the two noisier metrics: accuracy discards the probability entirely,
and ECE over a few bins is unstable at ~200 matches per season. Brier and log
loss never favour a model.

**This is not** "beats the bookmaker on some metrics" as a headline. The
aggregate result is unambiguous; the per-season exceptions are variance.

---

## 9. Calibration

Reported separately from classification accuracy, because they diverge here.

| Model | ECE ↓ | Accuracy ↑ |
|---|---|---|
| Bookmaker | **0.0678** | **68.6%** |
| Elo | 0.0762 | 62.1% |
| Ensemble | 0.0824 | 67.4% |
| Logistic | 0.0871 | 67.7% |
| Poisson | 0.0926 | 56.8% |
| XGBoost | 0.1226 | 65.8% |

Elo has the second-best calibration while having the second-*worst* accuracy —
a direct demonstration that the two must not be conflated. XGBoost is the clearest
counter-example in the other direction: mid-table accuracy, worst calibration by
a wide margin.

**The production ensemble's calibration is not measured here.**
`generate_recommendations` wraps logistic and XGBoost in `CalibratedModel`
(out-of-sample isotonic regression) before blending; the backtester fits them
raw. Calibrating two of four components individually does not imply the weighted
blend has lower ECE — averaging calibrated with uncalibrated probabilities can
move calibration either way. A production-equivalent number requires running the
calibration flow inside each fold, which this run does not do.

---

## 10. Betting / value simulation

Implemented in `backtesting/simulation.py`. **Weak evidence — read the caveats.**

| Selection | Value |
|---|---|
| Threshold | edge > 0.03 (model prob − implied prob) |
| Odds source | Squiggle Punters consensus, margin-free |
| Staking | Full Kelly, hard-capped at 5% of bankroll |
| Bets per match | At most one, on the higher-edge side |
| Sample | 931–1,299 simulated bets per model over 7 seasons |
| Transaction assumptions | None — no commission, no slippage, no stake limits, no line movement |

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
they do not equal wins ÷ bets. ROI *is* pooled. Per-fold win counts are not
retained in the aggregate, so the pooled hit rate cannot be recovered.

**These are not expected returns.** In order of severity:

1. **The prices carry no bookmaker margin.** Implied probabilities sum to exactly
   1.0. Real Australian H2H markets run at roughly 105–110% overround. Betting
   into margin-free prices is not achievable and inflates every ROI here.
2. **The "edges" concentrate on longshots.** All models regress strong favourites
   toward the mean, so they look most confident *relative to the market* on
   outsiders. That is a calibration weakness being mistaken for an edge. The ROI
   ordering is nearly the inverse of the forecast-quality ordering — what you
   would expect from variance, not skill.
3. **The sample is small and correlated.** ~1,200 simulated bets over seven
   seasons, many on the same teams in the same seasons. Bootstrap confidence
   intervals (`backtesting/bootstrap.py`) were **not** computed for this run
   (`bootstrap_cis` is empty in the artifact), so these point estimates carry no
   significance claim.

**No CLV is reported.** Closing-line value needs a real opening and closing price
per market; the historical feed provides one figure per match.
`evaluation/clv_tracker.py` computes CLV from live-captured snapshots during
paper trading, and that sample is not yet large enough to report.

---

## 11. Negative results

Recorded deliberately. These are the findings that did not go the desired way.

1. **No model beats the market.** The headline result. Best model 0.2056 against
   0.1997, ~3% worse, and worse on every other aggregate metric too.

2. **The ensemble does not beat its best component.** Blending logistic with
   three weaker models yields 0.2081 against logistic's 0.2056.

3. **The ensemble does not reduce variance relative to its best component
   either.** Across the seven folds its Brier standard deviation is 0.0182
   against logistic's 0.0170 — marginally *more* variable. What blending
   demonstrably damps is its heaviest component: XGBoost swings 0.0368, the blend
   containing it swings 0.0182. It protects against the worst component, not the
   best one.

4. **Nor does the blend buy calibration.** Its ECE (0.0824) sits between
   logistic's (0.0871) and Elo's (0.0762).

5. **XGBoost underperforms logistic regression** out of sample: 0.2269 vs 0.2056,
   the worst ECE in the table, and by far the widest fold-to-fold swing. This
   evaluation shows the underperformance; it does **not** establish the cause
   (see §12).

6. **Poisson is barely a model.** In score mode its GLM regresses on an intercept
   and `is_final` only — no team identity, no form, no market — so every
   regular-season match receives the same probability. Its accuracy (56.8%) is
   identical to always picking the home team.

7. **Hyperparameter tuning made results look better than they were.** The tuned
   configuration flattered Elo by 0.0021 Brier. Removing it was a correction, not
   an improvement.

8. **Player-availability features carry no signal at all.** Not merely
   approximate: `collectors/player_collector.py` hard-codes every historical
   lineup to availability 1.0 with zero absences, because retrospective lineups
   record only who *did* play. All 1,413 evaluation rows are identical, so the
   feature family contributes exactly nothing.

9. **Weather features carry no signal.** No historical weather was collected.
   The measurement columns (temperature, wind, precipitation) are 100% null; the
   derived flags are constant `0` and `weather_scoring_index` constant `1.0`.
   Either way the family contributes nothing.

10. **The apparent staking profits do not survive scrutiny.** The two models with
    positive simulated ROI (Elo +0.6%, XGBoost +0.4%) are the ones with the
    *worst* probability quality, on margin-free prices, without confidence
    intervals. See §10.

---

## 12. Interpretation

Kept separate from measurement on purpose.

### Observed (measured)

- Bookmaker consensus has the lowest Brier and log loss in aggregate and in all 7 seasons.
- Best model is 2.95% worse than the benchmark on Brier.
- Elo has the 2nd-best ECE and the 2nd-worst accuracy.
- XGBoost has the widest fold-to-fold Brier spread (SD 0.0368 vs logistic 0.0170).
- Poisson accuracy equals the always-pick-home rate to one decimal place.

### Interpretation (reasoned, not measured)

- **Why the market wins.** AFL head-to-head markets are liquid, and a consensus
  of bookmakers prices them with strictly more information than these features
  carry — including team news that never reaches the dataset. A model that *did*
  beat a near-closing consensus by a wide margin over 1,413 matches would be
  better evidence of leakage than of skill. The measured result is the credible
  one.
- **Why XGBoost struggles.** Overfitting on ~1,600 rows and 29 features is the
  natural reading, but this evaluation cannot establish it. Attributing a cause
  needs training-set scores, learning curves, or a nested tuning experiment,
  none of which this run produces.
- **Why the ensemble is still kept.** Not for accuracy or calibration, both of
  which it loses to logistic. It bounds the damage from its worst component,
  which matters when component quality can drift between retrains.

---

## 13. Reproducibility

| Field | Value |
|---|---|
| Commit | `a700ecd` |
| Evaluation run | 2026-08-19T08:28:38Z |
| Python | 3.11.15 |
| Libraries | scikit-learn 1.9.0, XGBoost 3.2.0, statsmodels 0.14.6, pandas 2.3.3, NumPy 2.4.6, SciPy 1.17.1 |
| Seeds | `random_state=42` (logistic, XGBoost); Elo and Poisson deterministic |
| Splits | By calendar season — no sampling |
| Artifact | `examples/backtest_2026-08-19.json` |

Full regeneration (needs network to the Squiggle API — free, no key; ~5 minutes):

```bash
# 0. Build the schema (required — ingestion writes to tables that must exist)
python -m alembic upgrade head

# 1. Fixtures and results, 2017 onward
for y in 2017 2018 2019 2020 2021 2022 2023 2024 2025; do
  python -m orchestration.jobs.ingest_afl --season $y
done

# 2. Historical market-consensus probabilities
python -m orchestration.jobs.backfill_squiggle_odds

# 3. Feature matrix
python -m orchestration.jobs.build_features

# 4. Walk-forward backtest. --untuned is not optional for publishable numbers.
python -m orchestration.jobs.run_backtest --min-season 2017 --max-season 2025 --untuned
```

**Not bit-reproducible from committed inputs alone.** The feature parquet is
gitignored, steps 1–3 depend on live Squiggle data that may be retroactively
corrected, and `requirements.txt` pins ranges rather than exact versions, so a
scikit-learn or XGBoost minor release can shift the numbers. Pinning a lockfile
and committing the parquet would fix this and has not been done.

For a fast, network-free look at the pipeline on one held-out round, run
`make demo` — but ten matches cannot evaluate a model. This page can.

---

## 14. Limitations

| Limitation | Detail |
|---|---|
| Zero bookmaker margin | Consensus implied probabilities sum to 1.0; real markets take 5–10%. Makes all simulated ROI structurally optimistic. |
| Synthetic odds timestamp | The feed has no capture time; snapshots are stamped 2h pre-match. True timing unknown, probably nearer kickoff. |
| Odds are a consensus, not a book | One market-consensus figure per match, not a specific bookmaker's tradeable price. |
| Sample size | 1,413 test matches; ~200 per season. Accuracy and ECE are unstable at that per-season size. |
| No confidence intervals | `bootstrap_cis` empty for this run. No significance claims are made. |
| No CLV | Not computable from a feed with one price per match. |
| Player availability | Constant 1.0 across the dataset — contributes nothing (§11.8). |
| Weather | Not collected. Measurements 100% null; derived flags constant (`0` / `1.0`). No signal either way. |
| Draws excluded | ~0.5% of matches dropped rather than modelled. |
| Production calibration unmeasured | Backtest fits raw components; production applies isotonic calibration (§9). |
| Tuning contamination | Avoided via `--untuned`, but the tuners themselves remain fold-contaminated by design (§7). |
| Not bit-reproducible | See §13. |
| Historical data only | No forward-tested live period is reported. |

Survivorship bias is **not** a material risk here: the dataset is the complete
fixture list for each season, not a surviving subset.

---

## 15. Verified claims

Safe to reuse as written.

- Expanding-window walk-forward evaluation over 7 AFL seasons (2019–2025 test folds), 1,413 settled matches.
- Six models evaluated against a bookmaker-consensus benchmark on Brier, log loss, accuracy and ECE.
- The bookmaker consensus achieves the best Brier and log loss in aggregate and in every individual test season.
- The best model (logistic regression, Brier 0.2056) finishes ~3% worse than the benchmark (0.1997).
- Temporal leakage is prevented by an assertion that raises on violation, not by convention, and is covered by tests.
- Reported metrics use untuned model defaults; tuned parameters are excluded because the tuners search the reported folds.
- Odds provenance was audited: 0 model-estimate fallbacks in 1,845 games across 2017–2025.
- Calibration is reported separately from accuracy, and the two diverge (Elo: 2nd-best ECE, 2nd-worst accuracy).

## 16. Unsupported claims

Current evidence does **not** establish these. Do not use them.

- ❌ "Beats the bookmaker" — in any framing. The benchmark wins in aggregate and on Brier/log loss in every season.
- ❌ "Beats the bookmaker on some metrics" as a headline — true only in isolated seasons on the two noisiest metrics, and misleading as a summary.
- ❌ "Profitable" / "positive ROI strategy" — simulated on margin-free prices, no confidence intervals, no transaction costs, and the positive-ROI models are the worst forecasters.
- ❌ "Well calibrated" as an unqualified claim — the benchmark is better calibrated than every model.
- ❌ "The ensemble improves accuracy / calibration / stability over its best component" — measured false on all three.
- ❌ "XGBoost overfits because of sample size" — a plausible reading, not a measured result.
- ❌ Any claim about live or forward performance — none has been tested.
- ❌ Any claim of statistical significance — no confidence intervals were computed.
