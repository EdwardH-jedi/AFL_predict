# Portfolio demo

`make demo` runs the modelling half of the pipeline end to end against bundled
sample data, with no API keys, no network access, and no PostgreSQL.

It is **not** a live system and does not pretend to be. It reads a frozen CSV
(`examples/sample_matches.csv`), trains the real models on the real code path,
and writes the same `predictions.json` contract the dashboard consumes.

See the repository `README.md` (Demo section) for the commands and
`docs/methodology.md` for what the models actually do.
