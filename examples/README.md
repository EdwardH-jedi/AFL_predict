# Example data and outputs

Everything here is **sample data for the portfolio demo**. None of it is a live
forecast, and nothing in this directory is used by the production pipeline.

| File | What it is |
|---|---|
| `sample_matches.csv` | 636 completed AFL matches (seasons 2023–2025) with the full pre-match feature set. Input to `make demo`. |
| `sample_predictions.json` | The `predictions.json` payload the static dashboard fetches, as produced by one demo run. |
| `sample_daily_summary.json` | The artifact shape `orchestration/jobs/generate_daily_summary.py` writes each day, as produced by one demo run. |
| `backtest_canonical.json` | The verified walk-forward backtest artifact behind every table in [`../docs/RESULTS.md`](../docs/RESULTS.md). Committed because `storage/raw_snapshots/` is gitignored, so a reviewer could not otherwise check the reported numbers against their source. Not demo output — regenerate it with the commands in that document. |

## Provenance of `sample_matches.csv`

Built by running the repository's own ingestion and feature pipeline against
public sources, then freezing the result:

```bash
python -m orchestration.jobs.ingest_afl --season 2023   # ... 2024, 2025
python -m orchestration.jobs.backfill_squiggle_odds
python -m orchestration.jobs.build_features
```

- **Match results, fixtures, venues, teams** — [Squiggle API](https://api.squiggle.com.au)
  (free, public, no key). Public sporting results.
- **Bookmaker probabilities** (`bm_*`) — Squiggle's Punters consensus feed, a
  market-consensus implied probability per match. See the caveats in
  [`../docs/RESULTS.md`](../docs/RESULTS.md): the consensus is margin-free
  (overround = 1.0) and carries no real timestamp, so the loader stamps it two
  hours pre-match.
- **Derived features** (Elo, form, rest, travel, venue, head-to-head) — computed
  by `features/extractors/` from the above, strictly pre-match.

Weather columns are present but empty: no historical weather was collected for
these seasons. The all-NaN measurement columns were dropped rather than shipped
as a wall of nulls.

**No credentials, account identifiers, bet slips, or personal data** appear in
any file here. The only sources are public results and public market prices.

## Regenerating

```bash
python -m demo.run_demo --write-example
```

That rewrites the two JSON files from the CSV. To rebuild the CSV itself you
need network access to the Squiggle API — see the commands above.
