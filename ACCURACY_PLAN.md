# AFL Predict — Accuracy Improvement Plan

> **Status: historical planning document (written 2026-04-10).** Much of what
> it diagnoses as missing has since been implemented — XGBoost and Poisson are
> trained by `train_models.py`, recommendations build a weighted ensemble,
> and the H2H / multi-scale form / venue-performance / travel / weather
> extractors and isotonic calibration all exist (see `docs/SYSTEM_REPORT.md`
> for the current architecture). The problem descriptions below describe the
> April 2026 state, not the present code.

## Current Baseline (as of 2026-04-10)

> **Caveat — read before citing these numbers.** This table is a historical
> snapshot from 2026-04-10 and has not since been reproduced; the repository
> does not bundle the dataset or backtest artifacts needed to regenerate it.
> The **Bookmaker Baseline row is not a valid market comparison**: as P1 below
> documents, bookmaker odds had ~0% coverage in the training data at the time,
> so that baseline was computed almost entirely from fallback values. **No
> "model beats the bookmaker" conclusion can be drawn from this table.** A real
> bookmaker baseline (with full odds coverage) is expected to be the hardest
> benchmark to beat — see `docs/backtesting.md`.

| Model              | Brier Score | Log Loss | Accuracy | Training Features     |
|--------------------|-------------|----------|----------|-----------------------|
| Logistic Baseline  | 0.1830      | 0.5397   | 69.0%    | 13 (ELO + form + venue) |
| ELO Baseline       | 0.2039      | 0.5889   | 67.1%    | Stateless             |
| Bookmaker Baseline | 0.2430*     | 0.6769*  | 62.5%*   | Implied prob only     |
| Always-Home Naive  | —           | —        | 56.9%    | None                  |

\* Computed with ~0% real odds coverage — not representative of bookmaker skill.

- **Best model beats always-home by +12.1 pp** — meaningful but room to grow
- **Brier reference**: 0.25 = coin-flip; 0.18 = decent; elite sports models reach ~0.16
- **Target**: Brier ≤ 0.17, Accuracy ≥ 71%, positive CLV over 50+ bet sample

---

## Diagnosed Problems (Priority Order)

### CRITICAL — Data gaps that cripple the model

**P1. No historical bookmaker odds (0% coverage in 2,266 settled matches)**
The single strongest pre-match predictor (`bm_home_implied_prob`, corr ≈ 0.45 with outcome)
is 100% NaN in all training data. The model cannot learn from market pricing at all.
Only 7 of 188 upcoming matches have odds ingested.

Squiggle API (`/games?year=YYYY`) returns historical H2H odds going back to at least 2020.
This is the highest-leverage fix in the entire project.

**P2. XGBoost and Poisson are implemented but never trained**
`train_models.py` only trains 3 models. `XGBoostModel` and `PoissonModel` exist in
`models/` but are never added to the training loop. No gradient boosting or score-based
predictions are ever generated.

**P3. Ensemble is never used in recommendations**
`models/ensemble.py` is fully implemented but `generate_recommendations.py` only
loads a single best model. A weighted blend of ELO + Logistic (even without odds)
would reduce variance and likely improve Brier score by 0.003–0.008.

### HIGH — Missing signal features

**P4. No head-to-head (H2H) historical record**
AFL teams play each other multiple times per year and across seasons. Some matchups
are historically lopsided regardless of current form. H2H win rate over last 5–10
meetings is a strong contextual signal absent from every current model.

**P5. Form window is fixed at 10 — no multi-scale features**
Currently only `l10` form is computed. Short-term momentum (L3, L5) and
season-to-date form capture different signals. A team 1–9 on season but 3–2 in
last 5 is trending differently to a team 5–5 overall but 1–4 in last 5.

**P6. No venue-specific performance features**
Each team's win rate at specific venues (home-ground advantage effect beyond the
binary `is_neutral_venue` flag) is unmodelled. Teams like Geelong at Kardinia Park
historically win >70% — this is venue-specific, not just ELO.

**P7. Score margin is not used as a training signal**
`home_win` (binary) is the target, but training on margin (points difference) as
an auxiliary signal and then converting to probability improves calibration.
The Poisson model already attempts this but falls back to scaled mode because
`home_score` is not passed in training data.

### MEDIUM — Model quality issues

**P8. ELO hyperparameters are untuned defaults**
K=32, home_advantage=50, regression=0.75 are reasonable defaults but not validated
against AFL data. K should likely be lower (AFL score variance is high) and
home advantage varies by venue type. No hyperparameter search has been done.

**P9. No calibration post-processing**
Logistic regression with L2 regularisation tends to be reasonably calibrated,
but no Platt scaling or isotonic regression calibration layer has been applied.
ECE has not been computed and logged systematically.

**P10. No interstate travel / fatigue features**
Flying Perth → Melbourne (or vice versa) is a known AFC fatigue factor.
West Coast / Fremantle interstate travel is unmodelled. Related to rest_days
but not captured by it (5 rest days at home ≠ 5 rest days with interstate travel).

### LOWER — Longer-horizon improvements

**P11. No player availability signal**
AFL weekly team selections are announced Thursday. Missing key players
(top-3 goalkickers, key defenders) materially shifts win probability.
The `features/extractors/player_availability.py` extractor exists but
produces empty features (not wired to any data source).

**P12. Weather data is 100% NaN in all settled data**
`weather_collector.py` and `WeatherExtractor` are implemented but never populated.
Wet/windy conditions reduce scoring variance and benefit underdogs slightly.

---

## Implementation Roadmap

### Phase 1 — Fix Critical Data Gaps (Week 1)
*Expected impact: Brier 0.183 → ~0.175, Accuracy → ~70–71%*

#### 1a. Backfill historical bookmaker odds from Squiggle
```
Squiggle API supports: GET /games?year=YYYY
Returns: tipsters' consensus + available bookmaker odds per game.
```
- Add `squiggle_odds_backfill` function to `collectors/squiggle_collector.py`
- Store as `OddsSnapshot` rows with `source="squiggle_historical"`
- Rebuild features parquet — bookmaker columns will populate for 2020–2025
- Re-run `train_models` — logistic and XGBoost now train on odds-aware features
- Expected: bookmaker implied prob (strongest single feature) becomes available

#### 1b. Wire XGBoost into train_models.py
- Add `XGBoostModel()` to the `models` list in `train_models._train_and_record`
- Add `is_neutral_venue` to `XGBoostModel.FEATURE_COLS` (currently missing)
- XGBoost handles nonlinear interactions (ELO × form × odds) that logistic misses
- Expected: XGBoost likely beats logistic once odds are available

#### 1c. Add weighted Ensemble to recommendations
- After training, construct `Ensemble([(elo, 0.3), (logistic, 0.4), (xgboost, 0.3)])`
- Wire into `generate_recommendations` as an option when all components load
- Ensemble selection criterion: use ensemble if all components are available,
  else fall back to best single model
- Expected: reduces per-match variance, smooths calibration

---

### Phase 2 — Enrich Features (Week 2)
*Expected impact: Brier ~0.175 → ~0.170, edge detection improves*

#### 2a. H2H extractor (`features/extractors/h2h.py`)
New features:
- `h2h_home_win_rate_l5`: home team's win rate in last 5 meetings vs this away team
- `h2h_avg_margin_l5`: average point margin in last 5 H2H meetings
- `h2h_games_played`: number of prior meetings (low = unreliable signal)

Implementation: single-pass over sorted match history, `dict[(home_id, away_id)] → deque`

#### 2b. Multi-window form (`FormExtractor` extension)
Add L3 and L5 windows alongside existing L10:
- `home_win_rate_l3`, `away_win_rate_l3`
- `home_win_rate_l5`, `away_win_rate_l5`
- `home_momentum`: difference between L3 and L10 win rate (trending up/down)
- `away_momentum`: same

The FormExtractor already supports configurable `window` — run it 3 times or
refactor to emit all windows in a single pass.

#### 2c. Venue win rate extractor (`features/extractors/venue_performance.py`)
New features:
- `home_venue_win_rate`: home team's historical win rate at this venue
- `away_venue_win_rate`: away team's win rate at this venue (as visitor)
- `venue_total_games`: sample size (low = unreliable)

Requires sufficient historical data per venue — use minimum 5 games threshold,
else emit NaN (imputer handles gracefully).

#### 2d. Fix Poisson score-mode training
Pass `home_score` and `away_score` columns through to `model.fit()` by including
them in `X_train` (currently `X_train.drop(columns=["home_win"])` doesn't drop
scores — they're already absent from the feature parquet). Fix: ensure score
columns flow into the parquet for settled matches from `MatchExtractor`.

---

### Phase 3 — Model Refinement (Week 3)
*Expected impact: Brier ~0.170 → ~0.165, calibration improves*

#### 3a. ELO hyperparameter search
Grid search over:
- K-factor: [16, 24, 32, 40] — AFL scoring variance may call for lower K
- Home advantage: [30, 40, 50, 60] — measured from data vs assumed 50
- Season regression: [0.65, 0.70, 0.75, 0.80]

Metric: Brier score on walk-forward validation (same expanding-window splits).
Write `backtesting/elo_tuner.py` that runs the grid and saves best params.

#### 3b. Calibration layer
After fitting each model, apply isotonic regression calibration using
`sklearn.calibration.CalibratedClassifierCV` or a post-hoc `IsotonicRegression`.
- Train calibration on a held-out calibration set (not the same validation set)
- Compare ECE before and after calibration
- Add calibrated model variant as `logistic_calibrated`

#### 3c. XGBoost hyperparameter tuning
Bayesian optimisation (optuna) or simple grid search over:
- `max_depth`: [3, 4, 5, 6]
- `learning_rate`: [0.01, 0.03, 0.05, 0.1]
- `n_estimators`: [200, 300, 500] (with early stopping)
- `subsample`: [0.7, 0.8, 0.9]

Use same walk-forward evaluation to avoid overfitting to a single season.

#### 3d. Feature importance analysis and pruning
After XGBoost trains, log `feature_importances_` (SHAP if available).
Remove features with near-zero importance to reduce overfitting:
- Likely low-importance: `home_avg_pts_against_l10` (corr with outcome is weak)
- Likely high-importance: `elo_diff`, `bm_home_implied_prob` (when available)

---

### Phase 4 — External Data Sources (Week 4+)
*Expected impact: incremental gains for specific match types*

#### 4a. Player availability signal
**Source**: Champion Data / AFL website announces teams Thursday ~6pm AEST.
- Scrape `footywire.com/afl/afl_match_centre.cgi` for team lineups once teams drop
- Store in `PlayerLineup` table (model already exists in `db/models/player_lineups.py`)
- Feature: `home_key_players_out` count, `away_key_players_out` count
- Wire `PlayerAvailabilityExtractor` (exists but empty) to this data source
- This is the single highest-value signal not yet modelled

#### 4b. Interstate travel features
New binary/ordinal feature in `RestDaysExtractor` or separate `TravelExtractor`:
- `home_interstate_travel`: True if home team flew in for this game
- `away_interstate_travel`: True if away team flew in for this game
- Team-to-venue mapping already exists in `collectors/venue_rules.py`

State lookup: if team's home state ≠ venue's state → interstate = True.
Add `state` field to `TEAM_HOME_VENUES` or derive from existing team state field.

#### 4c. Historical weather backfill
BOM (Bureau of Meteorology) provides historical observations by weather station.
Map AFL venues to nearest BOM station, backfill weather for all settled matches.
Priority: `weather_precip_mm` and `weather_wind_kmh` (both affect scoring style).

---

## Success Metrics & Checkpoints

After each phase, run `/backtest` and compare against current baseline:

| Checkpoint     | Target Brier | Target Accuracy | Target CLV  |
|----------------|-------------|-----------------|-------------|
| Current        | 0.183†      | 69.0%†          | Unknown     |
| After Phase 1  | ≤ 0.176     | ≥ 70.0%         | > 0         |
| After Phase 2  | ≤ 0.171     | ≥ 70.5%         | > 0         |
| After Phase 3  | ≤ 0.167     | ≥ 71.0%         | > +1%       |
| After Phase 4  | ≤ 0.163     | ≥ 71.5%         | > +2%       |

† Historical 2026-04-10 snapshot values (see caveat at the top of this file);
not since reproduced.

CLV (Closing Line Value) is the most important long-term metric — positive CLV
means the model consistently identifies value before the market closes.
Target: +1.5% average CLV over a 50+ bet live paper-trading sample.

---

## Quick Wins (can be done today)

These require minimal code change and have immediate impact:

1. **Run `/backtest` now** — no backtest results are in the DB yet; this establishes
   the fold-by-fold performance baseline and reveals which seasons the model
   struggles on (likely 2020 COVID season, short format)

2. **Add XGBoost to train_models** — it's already implemented; just add 3 lines
   to the models list in `train_models.py` and run `/train`

3. **Lower `min_edge_threshold` from 3% to 2%** — may surface more picks
   for evaluation sample building (needed for CLV tracking)

4. **Extend odds ingestion frequency** — currently run once daily; running before
   and after team announcement (Thu ~6pm AEST) captures line movement signal

5. **Verify Squiggle has historical odds** — call `GET /games?year=2023` and
   check for odds fields; if present, the backfill is a single afternoon's work
   and unlocks the strongest feature for all historical data
