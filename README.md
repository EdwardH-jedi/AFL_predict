# AFL Predict

Paper-trading-first AFL betting research system.

No live betting or real-money automation is intended in this repository.

## Current status

The repository now contains active work across API routes, feature extraction,
model training, recommendations, migrations, and machine-operation docs.
The current working tree is still under verification and should not be treated
as merge-ready without checking `docs/T6_MERGE_READINESS.md`.

## Architecture

```text
collectors/     raw data ingestion
features/       feature engineering
models/         prediction and calibration models
evaluation/     model scoring and readiness checks
orchestration/  daily pipeline jobs
api/            FastAPI service and dashboard endpoints
db/             SQLAlchemy models and migrations
config/         environment-based settings
tests/          unit and integration tests
storage/        summaries, artifacts, and local outputs
```

## Quick start

```bash
cp .env.example .env
bash bootstrap.sh
make serve
make pipeline
make test
```

## Review guidance

- Keep source changes separate from generated artifacts under `logs/`, `reviews/`, and `storage/`.
- Re-run training, backtesting, and readiness checks on the final intended tree before merge.
- Confirm dual-machine environment settings in `.env.example` before release or operator handoff.
- Use `docs/T6_MERGE_READINESS.md` for the current merge checklist and PR-splitting guidance.
