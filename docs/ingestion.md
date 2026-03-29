# Ingestion Layer — Architecture and Local Run Guide

## Architecture

Every ingestion run follows the same five-stage pipeline:

```
collect → parse → validate → transform → upsert
```

| Stage       | Location                             | Responsibility                                      |
|-------------|--------------------------------------|-----------------------------------------------------|
| collect     | `collectors/*_collector.py`          | HTTP requests, rate limiting, retry, raw snapshot   |
| parse       | `collectors/parsers/`                | Raw JSON → typed dataclasses (structural checks)    |
| validate    | `collectors/validators/`             | Business-rule checks (ranges, consistency, presence)|
| transform   | `collectors/transformers/`           | Dataclass → DB-ready kwargs dict                    |
| upsert      | `orchestration/jobs/ingest_*.py`     | Idempotent DB writes, logging, pipeline_run record  |

## Data Sources

| Source                  | Used for         | Auth          | Docs                             |
|-------------------------|------------------|---------------|----------------------------------|
| Squiggle (`squiggle.com.au`) | AFL fixtures, results, teams | None (User-Agent required) | https://api.squiggle.com.au |
| The Odds API (`the-odds-api.com`) | H2H decimal odds (AU region) | API key | https://the-odds-api.com/liveodds-api/ |

### Squiggle API

- Free, public, community-maintained.
- No API key. Set a descriptive `SQUIGGLE_USER_AGENT` in `.env`.
- Do not send more than one request per second (see `_REQUEST_DELAY_SECONDS` in
  `collectors/squiggle_collector.py`).
- Game dates are returned in **AEST/AEDT (Australia/Melbourne)** and converted
  to UTC on parse. See `collectors/parsers/squiggle_parser.py:_parse_match_time`.

### The Odds API

- Free tier: **500 requests/month** — roughly one daily AFL ingest per round.
- Register at https://the-odds-api.com and set `ODDS_API_KEY` in `.env`.
- Remaining requests shown in logs after each fetch (`x-requests-remaining` header).
- TODO: Confirm `tab` bookmaker key is available in your subscription tier.
  Fall-back preference order is configured via `ODDS_BOOKMAKER_PREFERENCE` in `.env`.

## Raw Snapshots

Every API response is saved to disk **before** any parsing:

```
storage/raw_snapshots/
  squiggle/
    teams_20250320T060000Z.json
    games_2025_20250320T060100Z.json
    games_2025_r5_20250320T060200Z.json
  odds_api/
    h2h_odds_20250320T070000Z.json
```

Use `collectors.snapshot_store.SnapshotStore.load_latest(label)` to replay a
snapshot without a network call:

```python
from collectors.snapshot_store import SnapshotStore
store = SnapshotStore("./storage/raw_snapshots", source="squiggle")
raw = store.load_latest("games_2025")
```

## Team Name Normalisation

Odds API team names (e.g. `"Richmond Tigers"`) differ from Squiggle canonical
names (e.g. `"Richmond"`). All normalization passes through:

```python
from collectors.team_normalizer import normalize
normalize("Richmond Tigers")  # → "Richmond"
```

If a new alias appears in logs as an unrecognised name, add it to
`ALIASES` in `collectors/team_normalizer.py`.

## Idempotency

| Table          | Deduplication key                                    | On conflict         |
|----------------|------------------------------------------------------|---------------------|
| `teams`        | `external_id` (Squiggle team ID)                     | Update mutable fields |
| `matches`      | `external_id` (Squiggle game ID)                     | Update schedule; settle result once |
| `odds_snapshots` | `(match_id, bookmaker, date(snapshot_time))`       | Update in-place     |

Results (`home_score`, `away_score`, `result`) are written **once** on the first
run where `complete=100`. They are never overwritten to protect settled bets.

---

## Local Run Instructions

### 1. First-time setup

```bash
# Clone and enter repo
cd AFL_predict

# Bootstrap (creates .venv, copies .env.example → .env, creates storage dirs)
bash bootstrap.sh
source .venv/bin/activate

# Edit .env — required entries:
#   ODDS_API_KEY=<your key from the-odds-api.com>
#   SQUIGGLE_USER_AGENT=<your descriptive user agent>
```

### 2. Initialise database

```bash
make db-init
# Output: Tables created.
```

### 3. Run tests (no network, no DB required)

```bash
make test
# or just the fast parser/validator/transformer tests:
pytest tests/test_squiggle_parser.py tests/test_odds_parser.py \
       tests/test_validators.py tests/test_transformers.py \
       tests/test_team_normalizer.py -v
```

### 4. Ingest AFL fixtures (Squiggle — no API key needed)

```bash
# All rounds for current season
make ingest-afl ARGS="--season 2025"

# Single round only (useful for testing)
make ingest-afl ARGS="--season 2025 --round 1"
```

Expected log output:
```
INFO  ==> ingest_afl: starting (season=2025, round=None)
INFO  squiggle_collector: fetching teams
INFO  squiggle_collector: fetching games season=2025 round=None
INFO  ==> ingest_afl: completed in 2.3s — 18 teams, 207/207 matches upserted.
```

### 5. Ingest odds (requires `ODDS_API_KEY`)

```bash
# Dry run — parse and log, no DB writes
make ingest-odds ARGS="--dry-run"

# Live run
make ingest-odds

# Save raw snapshot only (no parsing or DB)
make ingest-odds ARGS="--snapshot-only"
```

Expected log output:
```
INFO  ==> ingest_tab_odds: starting (dry_run=False, snapshot_only=False)
INFO  odds_api_collector: fetching aussierules_afl h2h odds (region=au)
INFO  odds_api_collector: 487 API requests remaining this month.
INFO  ==> ingest_tab_odds: completed in 1.1s — 9 written, 0 skipped (of 9 events).
```

### 6. Run the full daily pipeline

```bash
make pipeline
# Runs: ingest_afl → ingest_tab_odds → build_features → generate_recommendations → settle_results
```

### 7. Start the API

```bash
make serve
# → http://localhost:8000/health/
# → http://localhost:8000/fixtures/?season=2025
# → http://localhost:8000/docs
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ODDS_API_KEY not set` warning | Key missing from `.env` | Add `ODDS_API_KEY=<key>` to `.env` |
| `no DB match found for ...` | Odds ingested before fixtures | Run `make ingest-afl` first |
| Unknown team name in logs | New alias in odds feed | Add to `ALIASES` in `team_normalizer.py` |
| `401 Unauthorized` | Bad API key | Check `ODDS_API_KEY` in `.env` |
| `tenacity.RetryError` | Squiggle/Odds API down | Check source status; re-run later |
| Game result not settling | `complete` < 100 in source | Wait for Squiggle to mark it complete |

---

## Outstanding TODOs

```
TODO: collectors/squiggle_collector.py  — Verify Squiggle date field timezone
      against live data (documented assumption: AEST/AEDT via
      collectors/parsers/timezone_utils.py; confirm once live ingestion runs)

TODO: collectors/odds_api_collector.py — Confirm 'tab' bookmaker key is present
      in subscription tier before relying on it as primary source

TODO: collectors/team_normalizer.py    — Add any new aliases reported in
      end-of-run "unrecognised team name(s)" warnings from ingest_tab_odds
```
