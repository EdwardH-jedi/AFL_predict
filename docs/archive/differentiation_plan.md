# Differentiation Plan

**Purpose:** Ordered roadmap of future improvements most likely to increase genuine
prediction quality and operator decision support. Each item is grounded in current system
gaps — not speculation.

**Governing constraint:** No item should be started until paper trading data exists to
validate the improvement and the critical TODO fixes (model selection/loading) are complete.
See `docs/recommendation_quality_iteration.md` section 8.

---

## What this document is not

- Not a product roadmap. There is no product.
- Not a list of features to make the system look more complete.
- Not a schedule. These are ordered by value, not by when they should be built.

Items deliberately excluded from this plan:
- Sponsor, affiliate, or monetisation features
- Finance, portfolio, or bankroll management automation
- Narrative or commentary generation
- Mobile app or notification polish
- Any feature whose primary purpose is aesthetics

---

## Current capability baseline

Before adding anything, it is worth being precise about what the system currently does:

| Capability | Current state |
|-----------|--------------|
| ELO ratings | K=32, home adv=50, 25% season regression |
| Rolling form | 10-game win rate, pts for/against |
| Bookmaker features | Latest pre-match snapshot (implied prob, overround) |
| Rest days | Days since previous match per team |
| Venue | Raw string passthrough — **not encoded** |
| Head-to-head history | Not implemented |
| Player availability | Not implemented |
| Odds movement tracking | Single snapshot only — no movement data |
| Recommendation explanation | Match + side + odds + stake fraction — **no edge value, no model attribution** |
| Ensemble weighting | Static weights hardcoded in settings |

---

## Priority 1 — Fix model selection and loading (correctness, not differentiation)

**What:** Resolve the two critical TODOs in `generate_recommendations.py`:
1. Select the model with the lowest Brier score on validation data, not just the most recently trained.
2. Load the correct model class from the artifact based on `model_run.model_name`.

**Why this is first:** Until these are fixed, all recommendations come from `BookmakerBaseline`
regardless of what was trained. The system is comparing bookmaker-implied probability against
itself. Every subsequent improvement is built on this fix.

**Data required:** None. This is a code change only.

**Effort:** Small. The `ModelRun` table already stores `brier_score`. The artifact saving
infrastructure in each model already exists. This is a lookup and dispatch change.

**Files to change:**
- `orchestration/jobs/generate_recommendations.py` — `_load_best_model()`
- Possibly `models/base_model.py` — add a `from_artifact()` classmethod if not present

**Gate:** Do this before any paper trading results are interpreted.

---

## Priority 2 — Venue encoding: home-ground and neutral-ground flags

**What:** Replace the raw venue string passthrough in `VenueExtractor` with two binary features:
- `is_home_ground` — true if the home team's designated home venue matches the match venue
- `is_neutral_ground` — true if neither team's home venue matches (interstate blockbusters,
  finals at MCG, etc.)

**Why this matters:** AFL home-ground advantage is substantial and varies by team. The MCG
(Collingwood, Melbourne, Richmond home ground) draws 80,000+; suburban grounds draw 15,000.
Home crowd effects are real and persistent. The current ELO home advantage is a flat +50 for
all matches regardless of whether the home team is actually at their home ground.

This is also a leakage-safe feature — venue is known before the match.

**Data required:** A team → home_venue mapping. Available from Squiggle's `/teams` endpoint
(already collected in `storage/raw_snapshots/squiggle/`). Teams table exists in the DB.

**Effort:** Small. The `VenueExtractor` is already wired in. This adds a venue lookup against
the teams table and emits two boolean columns.

**Expected signal:** Research on AFL markets consistently shows venue as a top-5 feature.
Expected improvement: small ECE reduction and improved model accuracy on interstate matches.

**Files to change:**
- `features/extractors/venue.py`
- `db/models/teams.py` (add home_venue field if not present)
- `db/migrations/` (new migration if schema changes)

---

## Priority 3 — Line movement tracking

**What:** Collect and store multiple odds snapshots per match (currently only the latest
pre-match snapshot is used). Add features:
- `odds_open_home` / `odds_open_away` — first-available odds snapshot
- `odds_movement_home` — `(latest_odds - opening_odds) / opening_odds` (proportional drift)
- `odds_movement_direction` — shortened (negative = market cooling on team), lengthened (positive)
- `snapshot_count` — number of snapshots available for this match (proxy for data coverage)

**Why this matters:** Odds movement is one of the strongest publicly observable signals in
sports betting markets. When the market shortens a team from $2.20 to $1.95, sharp money has
moved in. When odds drift from $1.95 to $2.20, public money has not followed. The direction
and magnitude of movement prior to our "bet" provides a quality filter on top of raw edge.

A recommendation that is going with sharp movement is more trustworthy than one that is
going against it.

**Data required:** Multiple ingest runs per match — the collection job already supports this,
and each snapshot is stored in `odds_snapshots` with `snapshot_time`. The data is already
there if the pipeline runs daily. The gap is in feature extraction and model input.

**Effort:** Moderate.
- `BookmakerExtractor` needs to query the earliest snapshot (opening) and latest snapshot
  (current) separately and compute movement features.
- `MatchFeature` model needs new columns.
- A new migration is needed.
- The `LogisticBaseline` and `XGBoostModel` feature columns list needs updating.

**Expected signal:** Movement features are expected to improve XGBoost performance more than
ELO-based models. Run the backtest with and without movement features to confirm.

**Gate:** At least 2 weeks of daily odds ingestion must exist before this feature is meaningful.

---

## Priority 4 — Recommendation explanation quality

**What:** Surface the edge value, model attribution, and win probability in recommendation
output. Specifically:
- Add `home_win_prob`, `away_win_prob` to recommendation display (currently in `Prediction`
  table but not returned by `/dashboard/recommendations` or `/api/recommendations`)
- Add `edge` (model_prob - bm_implied_prob) to recommendation output
- Add `model_name` (which model generated this prediction) to recommendation output

**Why this matters:** The weekly review framework (`docs/weekly_review_framework.md`) section 8
identified that the operator cannot currently verify *why* a match was recommended vs. passed.
Without edge value in the output, the daily review in step C3 of the operation plan requires
manual cross-referencing with the database.

This is not a model improvement — it is surfacing information already computed and stored.

**Effort:** Small.
- `api/routes/recommendations.py` — join to `Prediction` and `ModelRun` tables
- `api/routes/dashboard.py` — include edge in `/dashboard/recommendations` output
- `orchestration/jobs/generate_daily_summary.py` — include edge in daily artifact

**Expected improvement:** Faster, more confident daily review. Better edge bucket analysis
in weekly reviews. No model change required.

---

## Priority 5 — Head-to-head history features

**What:** Add a per-match feature capturing recent head-to-head (H2H) history between the
two specific teams:
- `h2h_home_win_rate_l5` — home team's win rate vs. this specific opponent in last 5 encounters
- `h2h_home_win_rate_l10` — same over last 10 encounters
- `h2h_result_diff` — difference in wins (e.g., +2 means home team won 2 more of the last 5)

**Why this matters:** Some AFL match-ups have persistent structural imbalances (dominant teams
at specific venues, rivalries with consistent momentum, finals match-up patterns). Rolling form
against all opponents smooths this over. H2H features capture match-up-specific signal.

**Data required:** Match results table already exists in the DB with home/away team IDs and
results. No new data source needed. This is derived entirely from existing data.

**Effort:** Small-moderate.
- New `H2HExtractor` in `features/extractors/`
- Register in `DatasetBuilder`
- New columns in `MatchFeature`
- Migration

**Gate:** Requires at least 5 seasons of match data in DB. Current data appears to go back to
2015 (raw snapshot files observed) — gate is already met once ingest is complete.

**Expected signal:** Likely small but stable. Most useful for the XGBoost and ensemble models
which can detect non-linear interaction effects between H2H and current form.

---

## Priority 6 — Player availability impact scoring

**What:** Model the impact of key player absence on match outcome probability. This requires:
1. A data source for pre-match team selection / injury list
2. A scoring function: which player absences shift the win probability by how much?

**Why this matters:** AFL is highly personnel-dependent. Key forward (Coleman medalist-type)
or ruckman absence can shift effective win probability by 3–8 percentage points — larger than
the minimum edge threshold. The bookmaker adjusts for this; our model currently cannot.

A model that correctly accounts for availability changes when the bookmaker adjusts can either:
- Confirm the bookmaker's adjustment is correct (no edge)
- Identify cases where the bookmaker over- or under-adjusted (potential edge)

**Data required:** No reliable free automated source currently exists for AFL team selection
data. Potential sources:
- AFL official website (match-day team sheets, published 1–2 hours before game)
- Footywire.com — historical player stats, team selection history
- Manual entry for paper trading validation period

**Effort:** High. Data source identification and validation is the blocker, not the modelling.
A simple impact scoring approach (weighted sum of player ELO-equivalent ratings) can be
implemented once player data is available.

**Gate:** Do not begin until a reliable, automatable data source is identified and validated.
Manual entry during paper trading is acceptable for validation purposes only.

**Expected signal:** High potential. This is the most differentiated signal available in AFL
public-data prediction — most public models ignore it entirely.

---

## Priority 7 — Ensemble weight reoptimisation on live data

**What:** Periodically re-run the `Ensemble.optimize_weights()` procedure using accumulated
paper trading outcomes, not just backtest data. The current weights (bookmaker 0.30, ELO 0.10,
XGBoost 0.35, Poisson 0.25) are fixed in `config/settings.py`.

**Why this matters:** Model component quality shifts as the market changes, as new seasons
bring new team compositions, and as more training data accumulates. Static weights can
persist a component that has drifted in quality.

**Data required:** At least 60 settled paper-trade outcomes tied to specific model predictions.

**Effort:** Small — `Ensemble.optimize_weights()` is already implemented using scipy L-BFGS-B.
This is a periodic retraining task, not new infrastructure.

**Process:**
1. After 60+ settled bets: pull prediction vs. outcome data
2. Run weight optimisation
3. Compare optimised weights to current weights — if they differ by > 0.10 on any component,
   update `config/settings.py` and document
4. Retrain ensemble with new weights and run full backtest to confirm no degradation

**Gate:** 60 settled bets minimum. Do not reoptimise more than once per 30-day review period.

---

## Priority 8 — Operator decision-support: pre-match summary card

**What:** Extend the daily summary artifact and dashboard to include a structured pre-match
card for each upcoming recommended match, containing:

- Teams, venue, date/time
- Model predicted win probability (both sides)
- Bookmaker implied probability (both sides)
- Edge value (the actual signal)
- Whether odds have moved since opening (direction)
- Recommended side and stake fraction
- Model attribution (which model)
- Data freshness indicator for this specific match (is odds snapshot recent?)

**Why this matters:** The current daily review process (step C in the operation plan) requires
the operator to mentally join the JSON artifact sections to understand a recommendation.
A structured per-match card eliminates this. It also makes the CLV proxy check (weekly
review section 6) trivially easy — the operator can see at a glance whether odds moved
toward or away from our recommendation.

**Data required:** All data is already in the database. This is a query and output change only.

**Effort:** Small-moderate.
- `orchestration/jobs/generate_daily_summary.py` — new `_build_recommendation_cards()` function
- `api/routes/dashboard.py` — new or extended `/dashboard/summary` field
- No schema changes needed

**Gate:** Useful from day 1 of paper trading but not blocking. Build after Priority 4
(which adds edge to recommendation output — those changes compose cleanly here).

---

## Sequencing summary

| Priority | Item | Effort | Gate |
|---------|------|--------|------|
| 1 | Fix model selection/loading | Small | Now — blocks everything |
| 2 | Venue encoding (home/neutral ground) | Small | After Priority 1 |
| 3 | Line movement features | Moderate | After 2+ weeks of daily ingest |
| 4 | Recommendation explanation quality | Small | Any time |
| 5 | Head-to-head history features | Small-moderate | After Priority 1 |
| 6 | Player availability impact scoring | High | After reliable data source found |
| 7 | Ensemble weight reoptimisation | Small | After 60+ settled bets |
| 8 | Pre-match summary card | Small-moderate | After Priority 4 |

---

## What good differentiation looks like in this context

The AFL H2H market is reasonably efficient. The realistic ambition is to find:
- Situations where the market has not fully adjusted for a structural factor
  (venue, availability, unusual rest patterns)
- Situations where line movement signals that the market is correcting, and our model
  agrees with the direction

The differentiation work above is ordered to build toward that: fix the model pipeline,
add venue signal, add movement signal, add availability signal. That sequence, executed
carefully on real paper trading data, is more likely to find genuine edge than any amount
of model architecture experimentation without reliable input features.
