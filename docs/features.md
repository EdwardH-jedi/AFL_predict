# Feature Pipeline — Architecture and Local Run Guide

## Overview

The feature pipeline transforms raw match and odds data into a flat per-match
feature matrix. Each row represents one AFL match with all available pre-match
information that can legally be used for prediction.

Output:
- **Parquet snapshot** at `storage/raw_snapshots/features/features_{season}_{ts}.parquet`
- **DB table** `match_features` (for API serving and recommendation generation)

---

## Leakage Policy

**No future information may appear in feature columns for a given match.**

A feature for match M may only use information that was knowable strictly
*before* `match_time`. Specifically:
- ELO ratings: computed from results of all matches with `match_time < M.match_time`
- Rolling form: computed from results of all completed matches prior to M
- Bookmaker odds: only snapshots with `snapshot_time < M.match_time`
- Rest days: computed from `match_time` of prior matches (no result used)

The `home_win` column (target variable) is set to `None` for future/unplayed matches.
It is only populated once `result` is recorded in the `matches` table.

Leakage violations are logged as `ERROR` and counted. Any non-zero leakage
count in logs should be investigated immediately.

---

## Architecture

```
DatasetBuilder (features/feature_builder.py)
    │
    ├── EloExtractor       (features/extractors/elo.py)
    ├── FormExtractor      (features/extractors/form.py)
    ├── RestDaysExtractor  (features/extractors/rest.py)
    ├── VenueExtractor     (features/extractors/venue.py)
    └── BookmakerExtractor (features/extractors/bookmaker.py)
    │
    ├── features/validators.py   — leakage, null rate, range checks
    └── features/persistence.py  — parquet + DB upsert
```

Each extractor implements `BaseExtractor.extract(matches) -> dict[match_id, dict]`:
- Receives all matches sorted chronologically.
- Returns a mapping of `match.id → {feature_col: value}`.
- Maintains state internally (e.g. rolling ELO ratings, form queues).

---

## Feature Catalogue

### ELO Features

| Column         | Type  | Description                                              |
|----------------|-------|----------------------------------------------------------|
| `home_elo_pre` | float | Home team ELO rating immediately before this match       |
| `away_elo_pre` | float | Away team ELO rating immediately before this match       |
| `elo_diff`     | float | `home_elo_pre - away_elo_pre` (positive = home favourite)|

**ELO parameters:**
- Starting rating: 1500
- K-factor: 32
- Home advantage: +50 ELO points (for win probability calculation only)
- Season regression: ratings regressed 25% toward 1500 between seasons

### Rolling Form Features (last 10 games)

| Column                    | Type  | Description                                        |
|---------------------------|-------|----------------------------------------------------|
| `home_win_rate_l10`       | float | Fraction of last 10 games won by the home team     |
| `home_avg_pts_for_l10`    | float | Average points scored by the home team             |
| `home_avg_pts_against_l10`| float | Average points conceded by the home team           |
| `away_win_rate_l10`       | float | Fraction of last 10 games won by the away team     |
| `away_avg_pts_for_l10`    | float | Average points scored by the away team             |
| `away_avg_pts_against_l10`| float | Average points conceded by the away team           |

Form is computed from a team's perspective across all games (home and away).
For a team's first match, all form features are `None`.

### Bookmaker Features

| Column                | Type  | Description                                             |
|-----------------------|-------|---------------------------------------------------------|
| `bm_home_odds`        | float | Decimal H2H odds for home team win                     |
| `bm_away_odds`        | float | Decimal H2H odds for away team win                     |
| `bm_home_implied_prob`| float | Implied probability for home win (normalised)          |
| `bm_away_implied_prob`| float | Implied probability for away win (normalised)          |
| `bm_overround`        | float | Total implied probability (>1.0 = bookmaker margin)    |

Source: The Odds API (TAB preferred). The *latest* snapshot with
`snapshot_time < match_time` is used. `None` if no pre-match odds exist.

### Rest / Travel Features

| Column           | Type | Description                                          |
|------------------|------|------------------------------------------------------|
| `home_rest_days` | int  | Days since the home team's previous match (or None)  |
| `away_rest_days` | int  | Days since the away team's previous match (or None)  |

`None` for a team's first match of recorded history.

### Venue Feature

| Column  | Type | Description                     |
|---------|------|---------------------------------|
| `venue` | str  | Raw venue string from Squiggle  |

Categorical — useful for one-hot encoding or embedding. `None` if unknown.

**TODO:** Expand to `home_ground` (bool) and `neutral_ground` (bool) indicators.

### Target Variable

| Column     | Type | Description                              |
|------------|------|------------------------------------------|
| `home_win` | int  | 1 = home win, 0 = away win, None = other |

`None` for draws and unplayed matches. Draws are excluded from binary
classification training by convention.

---

## Local Run

### 1. Ensure fixtures and odds are loaded

```bash
make ingest-afl ARGS="--season 2025"
make ingest-odds
```

### 2. Build features

```bash
# Full pipeline (all seasons, write parquet + DB)
make build-features

# Season filter only
make build-features ARGS="--season 2025"

# Parquet only (skip DB upsert)
make build-features ARGS="--no-db"
```

Expected log output:
```
INFO  ==> build_features: starting (season=None, write_db=True)
INFO  DatasetBuilder: building features (season filter=None)
INFO  EloExtractor: ...
INFO  FormExtractor(window=10): ...
INFO  BookmakerExtractor: 180/207 matches have pre-match odds.
INFO  DatasetBuilder: built 207 rows × 22 columns (season=None).
INFO  persistence: saved 207 rows to storage/raw_snapshots/features/features_20250320T073012Z.parquet
INFO  build_features: match_features upsert — 207 inserted, 0 updated.
INFO  ==> build_features: completed in 1.4s — 207 rows.
```

---

## Dataset-Level Validation

After building the feature matrix, the following checks run automatically:

| Check         | Trigger                                     | Log level |
|---------------|---------------------------------------------|-----------|
| Leakage guard | `home_win` set on future match              | ERROR     |
| Leakage guard | result column present in feature row        | ERROR     |
| Null rate     | Column >30% null (excluding sparse columns) | WARNING   |
| Range check   | Value outside plausible AFL bounds          | WARNING   |

---

## Outstanding TODOs

```
TODO: VenueExtractor — add home_ground and neutral_ground binary flags
      once team home-venue data is available in the teams table.

TODO: FormExtractor — consider cross-season form continuity (currently
      form carries across seasons, which may introduce season-boundary bias).

TODO: BookmakerExtractor — support bookmaker preference ordering so the
      best available bookmaker is selected when multiple bookmakers exist
      for the same match.

TODO: Add head-to-head history features (team A win rate vs team B in
      last N encounters).

TODO: Add player availability features (injury lists, suspension data)
      if a suitable data source becomes available.
```
