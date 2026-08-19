# T6 Merge Readiness

Updated: 2026-04-18 (Australia/Sydney)

## Current repo state

- Branch: `main`
- Worktree: dirty
- Risk level: high

The current working tree mixes source changes, docs, scripts, generated daily summaries,
review artifacts, logs, and a nested repo pointer (`AFL_predict`). This is not ready for
one broad merge as-is.

## What appears to be changing

- API surface expansion: dashboard endpoints, sync/history routes, static assets.
- Pipeline and recommendation flow updates: `orchestration/`, `evaluation/`, `api/routes/dashboard.py`.
- Model/training changes: calibration, tuned params, ensemble loading, XGBoost wiring.
- Data/model schema changes: new migrations and model fields.
- Machine-operation updates: dual-machine environment settings and workflow docs.

## Merge guidance

1. Keep source-review PRs separate from generated/runtime artifacts.
2. Do not merge from `main` without first deciding whether a feature branch should hold this work.
3. Treat the nested repo `AFL_predict/` as a separate review concern until its purpose is confirmed.

## Files that should be reviewed separately from source changes

- `logs/**`
- `reviews/**`
- `storage/daily_summaries/**`
- `storage/model_artifacts/*.json`

These may be useful operational evidence, but they should not obscure code review.

## Verification still required

- Route smoke test for new API endpoints.
- Migration application on a clean database.
- `train_models` rerun on the final intended feature set.
- `run_backtest` or equivalent evaluation rerun after training changes.
- `make readiness` or live-readiness equivalent on the final tree.
- Confirmation that `.env.example` matches the intended dual-machine deployment model.

## Suggested PR split

1. Data/model foundations
2. Training/recommendation pipeline
3. Dashboard/API surface
4. Ops/docs and machine workflow

If this cannot be split, the PR body must call out the generated artifacts explicitly and explain why they are included.
