# AFL_predict — Preview/Review Narrative Generator: Master Implementation TODO

**Status:** PHASE 0 complete (inventory + design contract). Awaiting review before PHASE 1.
**Last updated:** 2026-06-17

## Project goal

AFL_predict produces structured numerical predictions. An RTX 5080 + local LLM
worker will later consume those structured outputs and generate accurate
human-readable AFL match previews and post-match reviews for the dashboard and
Discord.

## Architecture rule (non-negotiable)

- AFL_predict remains the **source of numerical truth**.
- The LLM **only explains stored structured data**.
- The LLM **never** calculates or changes win probabilities, recommendations,
  odds, stake, settlement, or bankroll.
- The core prediction/daily pipeline **must keep working** when the RTX 5080
  computer or LLM worker is offline.

## Working agreement

Phases are executed **sequentially**. After each phase:
1. run targeted validation (ruff + targeted pytest),
2. update this TODO,
3. report changed files and test results,
4. **stop** before beginning the next phase unless explicitly instructed.

---

## Progress overview

- [x] **PHASE 0** — Inventory and design contract
- [ ] **PHASE 1** — PredictionContext database foundation
- [ ] **PHASE 2** — Persist exact prediction-time snapshot
- [ ] **PHASE 3** — Poisson expected score and margin
- [ ] **PHASE 4** — Per-match XGBoost contributions
- [ ] **PHASE 5** — Canonical match context builder
- [ ] **PHASE 6** — Narrative job queue
- [ ] **PHASE 7** — RTX 5080 prompt-based inference worker
- [ ] **PHASE 8** — Validator and deterministic fallback
- [ ] **PHASE 9** — Dashboard and Discord integration
- [ ] **PHASE 10** — Post-match review generation
- [ ] **PHASE 11** — Human review dataset pipeline
- [ ] **PHASE 12** — Unsloth QLoRA

---

# PHASE 0 — INVENTORY AND DESIGN CONTRACT ✅

## 0.1 Checklist

- [x] Inspect the exact current implementation of the listed files
- [x] Document the current prediction flow
- [x] Identify the exact point where all individual model probabilities and the
      final feature row coexist
- [x] Define the intended relationships
- [x] Confirm `prediction_id` (not only `match_id`) is the canonical narrative key
- [x] Write the proposed schema and JSON contracts into this document

**Acceptance:** no production logic changed; file-level plan exists; uncertainties
are listed instead of guessed. ✅

## 0.2 Files inspected (with line anchors)

| File | Role | Key facts |
|---|---|---|
| `orchestration/jobs/generate_recommendations.py` | Prediction/rec fusion job | `run()` builds features (`:95`), predicts (`:131`), loops rows (`:134`), `_create_prediction_and_rec()` (`:367`) writes `Prediction`+optional `Recommendation`. Ensemble weights hardcoded (`:67`). |
| `models/base_model.py` | ABC | `predict_proba(X) -> DataFrame[match_id, home_win_prob, away_win_prob]` (`:33`). |
| `models/ensemble.py` | Weighted avg | Computes each component's probs (`:41-48`) then **discards them**, returns only the weighted mean (`:53-56`). Weights normalised in `__init__` (`:30`). |
| `models/xgboost_model.py` | XGB classifier | `_model` (XGBClassifier) + `_fit_features` (`:86-87`). 30 feature cols (`:25-60`). NaN handled natively. Wrapped in `CalibratedModel` in prod (see fusion job `:40`). |
| `models/poisson_model.py` | Poisson/score | Two modes: `score` (GLM on real `home_score`/`away_score`, `:80-101`) and `scaled` (isotonic on bm prob, `:118-129`). `mu_home`/`mu_away` are **real AFL points** but only exist in `score` mode (`:103-116`); discarded after win-prob conversion (`:47-55`). |
| `db/models/predictions.py` | Prediction row | Stores `match_id`, `model_run_id`, `home/away_win_prob`, `home/away_edge`, `kelly_home/away`, `created_at`. **No per-model probs, no feature snapshot.** |
| `db/models/model_runs.py` | Training run meta | Metadata only (name/version/metrics/artifact_path/`metadata_json` Text). No per-match data. |
| `db/models/match_features.py` | Pre-match features | **Subset** of the modelling feature set: ELO(3), L10 form only, bm odds, rest, venue, target. Missing h2h, l3/l5, momentum, weather, travel. `unique` on `match_id` → mutable, one row per match. |
| `db/models/matches.py` | Fixture+result | `home_score`/`away_score`/`result` nullable until settled (`:31-34`). |
| `db/models/recommendations.py` | Bet rec | `prediction_id` unique FK (`:15-17`) → one rec per prediction. |
| `db/models/bet_outcomes.py` | Settlement | `won`, `profit_loss_units`, `closing_odds`, `clv` (`:50-65`). FK to recommendation (unique). |
| `db/migrations/versions/*` | Alembic chain | Linear `0001→0002→0003→0005→0006→0007→0008`. **Head = 0008.** (0004 is a skipped number — next new revision is `0009`.) |
| `tests/conftest.py` | Test fixtures | Builds schema with **`Base.metadata.create_all()`** (`:49`), in-memory SQLite, fresh engine per test. **Tests do NOT run Alembic.** |

## 0.3 Current prediction flow (as built)

```
raw data (collectors: fixtures, odds, weather, players)
   │
   ▼
features/feature_builder.py  →  FeatureBuilder(db).build()  → flat feature DataFrame
   │   (one row per match, ~50 cols; also persists a NARROW subset to match_features)
   ▼
generate_recommendations.run()
   │  upcoming = df[home_win.isna() & match_time > now]          (:96)
   │  model, model_run = _load_best_model(db)                    (:86)
   │     └── _try_build_ensemble(): best run per component → Ensemble([(m, w)…])
   │  preds_df = model.predict_proba(upcoming)                   (:131)
   │     └── Ensemble.predict_proba():
   │           for each component: p = model.predict_proba(X)    (:45)  ← per-model probs EXIST here
   │           home_sum += p*w ; away_sum += p*w                 (:46-47) ← then DISCARDED
   │           returns ONLY [match_id, home_win_prob, away_win_prob]    (:53-56)
   │  for each pred_row:                                          (:134)
   │     match_row = upcoming[match_id == …]                      (:135)  ← full feature row EXISTS here
   │     _create_prediction_and_rec(db, pred_row, match_row, model_run)  (:136)
   │        → Prediction(home/away_win_prob, edge, kelly)         (:387)
   │        → Recommendation if edge ≥ threshold                  (:401-422)
   ▼
settle_results.run() (after match result)
   │  Prediction.match_id → Match.result ; build BetOutcome(won, pl, clv)
   ▼
dashboard /performance, generate_predictions_json.py
```

## 0.4 The fusion point — KEY FINDING

> **Today there is NO single point where individual model probabilities AND the
> final feature row coexist.**

- The **full feature row** is available in the `for` loop at
  `generate_recommendations.py:134-136` (`match_row` from `upcoming`).
- The **individual component probabilities** are computed inside
  `Ensemble.predict_proba()` (`ensemble.py:41-48`) and **discarded** — only the
  weighted mean survives to `preds_df`.

**Consequence for PHASE 2:** capturing per-model probabilities requires either
(a) adding a non-breaking `predict_proba_components()` / `predict_with_details()`
to `Ensemble` that returns per-component probs alongside the ensemble result, or
(b) re-invoking each component in the fusion job. Option (a) is preferred (single
forward pass, no recompute, no duplicated logic). **This is a design decision to
confirm before PHASE 2 — see Open Questions.**

Note: `Prediction.model_run_id` points to **one component run** (xgboost or
logistic, `:236-238`), NOT an "ensemble" ModelRun. The real ensemble composition
and weights therefore must be recorded in `PredictionContext.model_probabilities_json`,
not inferred from `model_run_id`.

## 0.5 Intended relationships

```
Match (1) ──< (N) Prediction          # a match may be predicted multiple times
Prediction (1) ── (1) PredictionContext   # immutable snapshot, NEW (PHASE 1)
Prediction (1) ── (0..1) Recommendation   # existing
Prediction (1) ──< (N) NarrativeJob       # preview + optional review (PHASE 6)
        - preview job: created after context is persisted
        - review  job: created only after result + settlement exist
```

## 0.6 Canonical key — CONFIRMED

`prediction_id` is the canonical narrative context key, **not** `match_id`.
Reason: the same match can receive multiple predictions at different times
(`Match (1) ──< (N) Prediction`), each with its own probabilities, odds snapshot,
and feature state. A review must compare the **specific** pre-match snapshot that
was shown, so context, narrative jobs, and the builder all key on `prediction_id`.

## 0.7 Proposed schema — `PredictionContext` (PHASE 1)

ORM model `db/models/prediction_context.py` (mirrored by Alembic `0009`):

| Column | Type | Null | Notes |
|---|---|:--:|---|
| `id` | Integer PK | no | autoincrement |
| `prediction_id` | Integer FK→predictions.id | no | **unique** (one immutable context per prediction) |
| `schema_version` | String(20) | no | e.g. `"1.0"`; bump on shape change |
| `feature_snapshot_json` | JSON | no | full feature row actually passed to models (all cols), JSON-safe |
| `model_probabilities_json` | JSON | no | ensemble + per-component probs + weights (shape below) |
| `score_projection_json` | JSON | yes | Poisson expected scores/margin or null (PHASE 3) |
| `explanation_json` | JSON | yes | XGBoost per-row drivers or null (PHASE 4) |
| `data_cutoff_at` | DateTime | yes | newest data timestamp included in the prediction |
| `created_at` | DateTime | no | `server_default=func.now()` |

**JSON column type:** use SQLAlchemy generic `sa.JSON` (SQLite-compatible: stored
as TEXT, serialized via `json`). The existing convention stores JSON as `Text`
via manual `json.dumps` (e.g. `model_runs.metadata_json`). `sa.JSON` is cleaner
and avoids hand-serialisation, but is a slight convention change — flagged in
Open Questions. Serialization helpers (NumPy/pandas/NaN/inf) are required either
way because `sa.JSON` uses the stdlib encoder which rejects `np.float64`/`NaN`.

### `model_probabilities_json` shape (proposed)

```jsonc
{
  "ensemble_method": "weighted_average",
  "final": { "home_win_prob": 0.67, "away_win_prob": 0.33 },
  "components": [
    { "model": "xgboost",          "weight": 0.35, "calibrated": true,
      "home_win_prob": 0.65, "away_win_prob": 0.35 },
    { "model": "logistic_baseline","weight": 0.30, "calibrated": true,
      "home_win_prob": 0.69, "away_win_prob": 0.31 },
    { "model": "poisson",          "weight": 0.20, "calibrated": false,
      "home_win_prob": 0.70, "away_win_prob": 0.30 },
    { "model": "elo_baseline",     "weight": 0.15, "calibrated": false,
      "home_win_prob": 0.66, "away_win_prob": 0.34 }
  ]
}
```
> `final.home_win_prob` MUST equal `Prediction.home_win_prob` (PHASE 2 test).
> If a single-model fallback is used, `components` has one entry, weight 1.0.

### `score_projection_json` shape (PHASE 3, nullable)

```jsonc
{
  "source_model": "poisson",
  "mode": "score",               // null/absent when poisson ran in "scaled" mode
  "units": "afl_points",         // do NOT label as AFL points until verified in P3
  "expected_home_score": 92.3,
  "expected_away_score": 84.1,
  "expected_margin": 8.2,        // home - away
  "model_version": "0.1"
}
```

### `explanation_json` shape (PHASE 4, nullable)

```jsonc
{
  "explained_model": "xgboost",
  "method": "pred_contribs",     // native xgboost; external shap only if required
  "output_space": "margin",      // pre-calibration raw margin, NOT ensemble prob
  "base_value": 0.12,
  "raw_output": 0.74,
  "positive_drivers": [
    { "feature": "elo_diff", "observed_value": 85.0, "contribution": 0.21,
      "direction": "home", "label": "ELO gap" }
  ],
  "negative_drivers": [
    { "feature": "away_win_rate_l5", "observed_value": 0.8, "contribution": -0.14,
      "direction": "away", "label": "Away recent form" }
  ]
}
```
> Scoped to the XGBoost component only. MUST NOT be presented as an explanation
> of the final ensemble probability.

## 0.8 Proposed contract — `MatchContext` (PHASE 5, preview of the design)

Versioned Pydantic. `build_match_context(prediction_id, mode) -> MatchContext`.
Top-level: `schema_version, mode(preview|review), prediction_id, match,
prediction, model_probabilities, score_projection, market, key_stats,
model_explanation, actual_result?, settlement?, data_freshness, missing_data`.
`key_stats` is a curated subset (ELO, recent form, H2H+sample size, rest/travel,
venue, market odds, odds movement/weather/players only when explicitly present) —
the **full** raw snapshot stays in the DB for audit, not in the LLM contract.
Full field-level spec to be finalised at PHASE 5.

## 0.9 Open questions / uncertainties (surfaced, not guessed)

1. **Per-component prob capture mechanism (blocks PHASE 2).** Add
   `Ensemble.predict_with_details()` returning per-component probs in one pass
   (preferred), vs re-invoking components. Confirm before PHASE 2.
2. **Calibration layer.** XGBoost & logistic are wrapped in `CalibratedModel`
   in production (`generate_recommendations.py:40`). Does the per-component prob
   we store represent the **calibrated** output (what feeds the ensemble) — yes,
   recommended — and does `pred_contribs` (PHASE 4) explain the **pre-calibration**
   margin? If so, `explanation_json.output_space` must say so explicitly.
3. **JSON storage type.** `sa.JSON` (proposed) vs project's existing `Text`+
   `json.dumps` convention. Pick one for consistency.
4. **`data_cutoff_at` source.** No explicit per-prediction data-cutoff timestamp
   exists today. Candidate: max odds `snapshot_time` / feature `feature_computed_at`
   for the match, or fall back to `Prediction.created_at`. Decide in PHASE 2.
5. **Single-model fallback.** When `_load_best_model` returns a single model
   (not an ensemble), `model_probabilities_json.components` has one entry — confirm
   that is acceptable and that the builder/validator handle it.
6. **Two schema paths.** Tests use `create_all`; production uses Alembic. Every
   new table needs BOTH an ORM model AND a matching `0009+` migration, kept in
   sync. PHASE 1 must add an explicit Alembic-from-fresh test since conftest does
   not exercise migrations.
7. **Poisson availability.** Score projection is only produced in `score` mode;
   in `scaled` mode there is none → `score_projection_json = null`. Preview text
   must tolerate absence.

---

# PHASE 1 — PREDICTION CONTEXT DATABASE FOUNDATION

**Goal:** immutable record of what the pipeline knew at prediction time.

- [ ] Add `PredictionContext` ORM model (`db/models/prediction_context.py`)
- [ ] Fields: `id, prediction_id FK, schema_version, feature_snapshot_json,
      model_probabilities_json, score_projection_json?, explanation_json?,
      data_cutoff_at?, created_at`
- [ ] Explicit relationship to `Prediction` (back_populates)
- [ ] Unique constraint on `prediction_id`
- [ ] Use DB JSON types with SQLite compatibility
- [ ] Forward-only Alembic migration `0009` (down_revision `0008`)
- [ ] Migration verified: fresh empty SQLite; from current head; no rewrite of
      old migrations; no production-data mutation
- [ ] Serialization helpers: NumPy int/float/bool, pandas Timestamp, datetime,
      NaN/inf, nullable
- [ ] Tests: create context; load back; relationship; uniqueness; JSON-safe
      conversion; **fresh Alembic migration runs**

**Acceptance:** existing prediction workflow unchanged; no SHAP/Poisson/queue/LLM
yet; fresh-database test passes; existing DBs upgrade safely.

---

# PHASE 2 — PERSIST THE EXACT PREDICTION-TIME SNAPSHOT

**Goal:** store exact model inputs + individual model outputs at prediction time.

- [ ] Modify prediction-creation path at the point a `Prediction` row is created
- [ ] Persist the exact feature row actually passed to the models
- [ ] Do NOT reconstruct features later from `_latest_` CSV/parquet
- [ ] Persist per-model probs where available: xgboost, poisson, elo, bookmaker,
      logistic/others, + ensemble/final
- [ ] Store model identity via stable registered names
- [ ] Include ensemble weights if exposed
- [ ] Store final home/away probabilities
- [ ] Record `data_cutoff_at` (newest data included)
- [ ] Create `PredictionContext` even when NO `Recommendation` is produced
- [ ] Rerun behavior: each Prediction gets its own context; never overwrite older
      context; never silently update historical snapshots
- [ ] Handle missing/stateless models without failing the pipeline
- [ ] Tests: prediction creates context; full snapshot stored; per-model probs
      stored; ensemble prob == `Prediction.home_win_prob`; two runs → two
      immutable contexts; rec absence still stores context; deleting CSVs does not
      block context retrieval

**Acceptance:** historical context reconstructable from DB alone; recommendation
selection unchanged; no recompute for historical rows.

---

# PHASE 3 — POISSON EXPECTED SCORE AND MARGIN

**Goal:** expose/store the score projection already computed by Poisson.

- [ ] Inspect meaning/units of `mu_home`/`mu_away` (verify real AFL points)
- [ ] Do not label "expected AFL score" until units verified
- [ ] Preserve `predict_proba()` interface
- [ ] Add `predict_score()` / `predict_with_details()` (non-breaking)
- [ ] Return: expected_home_score, expected_away_score, expected_margin,
      source_model, units, model_version?
- [ ] Save into `PredictionContext.score_projection_json`
- [ ] Null when projection unavailable (scaled mode)
- [ ] Tests: predict_proba unchanged; details match same internal params;
      margin = home − away; missing-model path safe; survives DB serialization

**Acceptance:** no duplicate/inconsistent Poisson calc; preview can state a
projected score/margin; units documented.

---

# PHASE 4 — PER-MATCH XGBOOST CONTRIBUTIONS

**Goal:** factual per-row evidence for the XGBoost component's probability.

- [ ] Prefer native `pred_contribs=True`; avoid external `shap` unless required
- [ ] Add `explain()` / `predict_with_explanation()` without breaking predict_proba
- [ ] Per row: explained_model, base_value, raw_margin/logit, positive_drivers,
      negative_drivers
- [ ] Each driver: feature, observed_value, contribution, direction, optional label
- [ ] Keep only top-k +/- drivers in `explanation_json`
- [ ] Keep full snapshot separately in `feature_snapshot_json`
- [ ] Verify: base_value + Σ(contributions) ≈ raw output (tolerance)
- [ ] Distinguish XGBoost explanation vs final ensemble probability
- [ ] Never claim XGBoost SHAP fully explains the ensemble
- [ ] Handle unavailable XGBoost artifacts gracefully
- [ ] Tests: contribution rows match input rows; sum check; ordering; missing
      values; feature-name alignment; pipeline succeeds without explanation

**Acceptance:** drivers persisted in `explanation_json`; scoped to XGBoost;
ensemble probs and betting logic unchanged.

---

# PHASE 5 — CANONICAL MATCH CONTEXT BUILDER

**Goal:** one stable input contract for previews/reviews/dashboard/Discord/QLoRA.

- [ ] Versioned Pydantic schemas (`MatchContext` + nested)
- [ ] `build_match_context(prediction_id, mode: "preview"|"review") -> MatchContext`
- [ ] `prediction_id` is the canonical lookup key
- [ ] Curate `key_stats` (ELO, form, H2H+sample, rest/travel, venue, market odds,
      odds movement/players/weather only when explicitly present)
- [ ] Do NOT pass all raw feature columns into the LLM contract
- [ ] Keep full raw snapshot in DB for auditing
- [ ] Include `missing_data` flags
- [ ] Review mode: require completed match or return not-ready; include original
      snapshot + actual result + BetOutcome/P&L/odds/CLV where available
- [ ] Internal API `GET /internal/predictions/{prediction_id}/context` (authenticated)
- [ ] Do not expose internal worker endpoints without auth
- [ ] Schema snapshot tests

**Acceptance:** preview & review share one versioned contract; historical context
built without mutable latest-feature files; missing info explicit, never fabricated.

---

# PHASE 6 — NARRATIVE JOB QUEUE

**Goal:** asynchronous, optional narrative generation.

- [ ] `NarrativeJob` ORM model (id, prediction_id, job_type, status, attempts,
      max_attempts, input_context_json, output_json?, validation_json?,
      error_message?, worker_id?, claimed_at?, lease_expires_at?, completed_at?,
      created_at, updated_at)
- [ ] Unique protection on `prediction_id + job_type`
- [ ] Migration
- [ ] Create preview jobs after context persistence
- [ ] Create review jobs only after result + settlement available
- [ ] Job-creation failure must NOT fail numerical prediction/settlement
- [ ] Authenticated internal endpoints: claim / complete / fail / (heartbeat?)
- [ ] Claim leasing: atomic claim, lease expiry, abandoned reclaim, retry count,
      max attempts
- [ ] Internal API token from env var; no secrets in source control
- [ ] Tests: dup prevention; atomic claim; retry; expired-lease reclaim; max
      attempts; worker offline doesn't break daily pipeline; preview/review split

**Acceptance:** prediction & settlement work without the RTX worker; pending jobs
queue safely; no duplicate Discord/dashboard narrative from duplicate jobs.

---

# PHASE 7 — RTX 5080 PROMPT-BASED INFERENCE WORKER (no QLoRA yet)

**Goal:** standalone worker for the RTX 5080 machine.

- [ ] Separate worker entry point/config
- [ ] Flow: claim job → receive MatchContext → generate structured JSON (local
      instruct model) → parse → validate → complete/fail
- [ ] Configurable backend: local Transformers / Unsloth-compatible loading /
      optional later adapter path / model path via env var
- [ ] Output schema: headline, summary, key_factors, risk_note, confidence_note,
      optional discord_summary
- [ ] System-prompt rules: facts-only; preserve numbers; no invented
      players/injuries/weather/quotes/standings/tactics/history; distinguish model
      vs bookmaker prob; distinguish XGBoost drivers vs ensemble; never alter
      side/odds/stake/P&L/result/CLV; no certainty language; state missing context;
      valid JSON only
- [ ] Record: inference model name, version/path id, prompt version, gen params,
      raw output, parsed output, latency, worker_id
- [ ] Graceful timeout + OOM handling
- [ ] Tests with a fake inference backend

**Acceptance:** worker processes jobs (API-based, no direct DB needed); invalid
output never reaches dashboard/Discord; numerical pipeline independent.

---

# PHASE 8 — VALIDATOR AND DETERMINISTIC FALLBACK

**Goal:** never trust generated prose without validation.

- [ ] Validate output team names match input
- [ ] Validate all mentioned numbers: win probs, expected scores, margins, ELO
      diffs, odds, edge, stake, actual result, P&L, CLV
- [ ] Reject unsupported entities (players, injuries, coaches, weather, tactics,
      history, quotes, rankings) unless explicitly in MatchContext
- [ ] Validate model favourite vs bookmaker favourite vs recommended side as
      separate concepts
- [ ] Detect invalid JSON, missing fields, excess length, unsafe markup
- [ ] Deterministic template fallback on timeout/invalid JSON/fact mismatch/
      unsupported claim/model offline
- [ ] Store validation result + `fallback_used`
- [ ] Tests with deliberate hallucinations and modified numbers

**Acceptance:** no unvalidated LLM text reaches users; fallback preserves exact
values; validation failure observable in job records/logging.

---

# PHASE 9 — DASHBOARD AND DISCORD INTEGRATION

**Goal:** display generated text without replacing numerical truth.

- [ ] Preserve all existing numeric prediction/performance views
- [ ] Dashboard preview fields: headline, summary, key factors, risk note,
      narrative status, generated model, generated timestamp, fallback indicator
- [ ] Review fields: original prediction, actual result, outcome, P&L, CLV,
      generated review, missing-data note
- [ ] Discord output only after successful validation or deterministic fallback
- [ ] Discord shorter than dashboard text
- [ ] Prevent duplicate sends via stable delivery record/idempotency key
- [ ] Never send betting language when there is no Recommendation
- [ ] Separate prediction narrative / betting recommendation / post-match review
- [ ] Tests: completed display; pending; failed; fallback; dup Discord prevention;
      no-recommendation case

**Acceptance:** dashboard works when no narrative exists; Discord never receives
unvalidated content; existing numeric API contracts do not regress.

---

# PHASE 10 — POST-MATCH REVIEW GENERATION

**Goal:** honest comparison of original prediction vs actual result.

- [ ] Build review context strictly from the original `PredictionContext`
- [ ] Never regenerate historical features using current data
- [ ] Include: original prob; original per-model probs; original projected
      score/margin; original recommendation+stake; actual score/result;
      settlement; P&L; CLV; post-match stats only when explicitly collected
- [ ] Review categories: successful bet; correct favourite no bet; incorrect
      winner; close upset; calibration miss; good CLV but losing; unavailable
      settlement
- [ ] If post-match stats absent: do not invent tactical reasons
- [ ] Safe fallback wording for unattributable misses
- [ ] Tests for all review categories

**Acceptance:** review tied to immutable pre-match snapshot; no hindsight
modification; tactical causes only when supported by stored data.

---

# PHASE 11 — HUMAN REVIEW DATASET PIPELINE

**Goal:** collect safe training data before QLoRA.

- [ ] Store: input_context_json, prompt_version, raw_model_output,
      validated_output, fallback_used, human_approved, human_edited_output,
      reviewer timestamp, inference model identifier
- [ ] Simple approval/edit workflow
- [ ] Export only approved examples
- [ ] Dataset validation: JSON schema valid; no missing prediction_id; no
      unsupported entities; numbers match source context; no duplicates;
      train/val split avoids same-match leakage
- [ ] Separate task tags: preview / review

**Acceptance:** dataset reproducible from DB; only approved/edited outputs train;
source context stays linked.

---

# PHASE 12 — UNSLOTH QLORA (only after enough approved data)

- [ ] Do not train on raw unvalidated generations
- [ ] Objective: style consistency, concise AFL wording, stable JSON, correct
      uncertainty language, reduced repetition
- [ ] Not a replacement for numerical prediction models
- [ ] Versioned training dataset
- [ ] Reproducible Unsloth training config
- [ ] Save: base model, adapter version, dataset version, training params, val results
- [ ] Evaluate vs prompt-only baseline: factual accuracy, numeric preservation,
      unsupported-claim rate, JSON validity, human preference, latency
- [ ] Deploy adapter only if ≥ prompt-only baseline accuracy

**Acceptance:** QLoRA improves style without lowering factual accuracy; adapter
deployment optional/reversible; prompt-only worker remains fallback.

---

# GLOBAL CONSTRAINTS

- Do not change AFL win prediction logic unless required to expose existing outputs.
- Do not change recommendation thresholds, Kelly, bankroll, or settlement logic.
- Do not change model selection criteria.
- Do not delete historical artifacts, predictions, or outcomes.
- Do not rewrite old migrations unless a demonstrated bug requires a minimal fix.
- Do not rely on mutable `_latest_` feature files for historical review.
- Do not make the daily pipeline depend on the LLM worker.
- Keep all narrative schemas versioned.
- Keep comments and documentation in English.
- Do not commit or push unless explicitly instructed.
- Avoid broad refactors.
- Run ruff and targeted tests for every phase.
- Preserve the current known test baseline; report pre-existing failures separately.
- Never claim a test passed unless it was actually run.

# REPORT FORMAT AFTER EACH PHASE

1. Phase completed
2. Root problem addressed
3. Files changed
4. Migration added or modified
5. Database compatibility
6. API/schema changes
7. Tests and exact results
8. Remaining risks
9. TODO document updates
10. Recommended next phase
