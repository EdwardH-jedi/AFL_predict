# T6 Merge Readiness — Closeout

Updated: 2026-10-15 (Ruff/CI baseline refresh — see "Full validation baseline
(2026-10-15)"); previous: 2026-08-25 (verification closeout pass)
Original checklist: 2026-04-18 (Australia/Sydney)

## Verdict

**CLOSED — the working tree is committed, clean, and verified at the code level.**
The 2026-04-18 concerns (dirty worktree mixing source, docs, and generated
artifacts; nested repo pointer) no longer describe the repository: all work is
committed on `main`, the tree is clean, and no nested gitlink exists
(`git ls-files -s | grep 160000` returns nothing).

What remains open is **not a code blocker but an evidence limitation**:
historical model-performance numbers cannot be reproduced from this repository
alone (no bundled dataset, database, or backtest-result artifacts), so the
docs must not — and now do not — claim verified predictive performance. See
"Not verifiable locally" below.

## Original "Verification still required" — item-by-item result

| Item | Status | Evidence (2026-08-25, Python 3.11.9, Windows) |
|---|---|---|
| Route smoke test for new API endpoints | **Verified** | TestClient-based suites pass: `test_health.py`, `test_dashboard_contract.py`, `test_quant_dashboard_static.py` (part of the 313-passing run below) |
| Migration application on a clean database | **Verified** | `tests/test_alembic_fresh_db.py` passes; additionally `alembic upgrade head` (0000→0008) ran clean against a throwaway SQLite DB |
| `train_models` rerun on final feature set | **Not verifiable locally** | Requires ingested historical data (external APIs); no dataset is bundled. Docs no longer rest any claim on a prior training run |
| `run_backtest` / evaluation rerun | **Not verifiable locally** | Same data dependency; `storage/backtest_results/` contains no artifacts. Performance tables in `docs/planning/ACCURACY_PLAN.md` are now explicitly caveated as unreproduced historical snapshots |
| `make readiness` on the final tree | **Verified (smoke)** | `python -m evaluation.live_readiness` runs end-to-end against a fresh DB and correctly reports `not_ready` (insufficient samples, TAB bookmaker unconfirmed) — the expected result with no betting history |
| `.env.example` matches dual-machine model | **Verified** | `NODE_ROLE` present with `standalone`/`collector`/`predictor` semantics documented in `config/settings.py` and `CLAUDE.md` |

## Full validation baseline (2026-08-25)

- `pytest tests/` — **313 passed, 1 skipped** (skip is by design: no static
  critical TODOs are currently defined), 1 deprecation warning (Pydantic
  class-based config in `api/routes/fixtures.py`).
  - One test defect was found and fixed during this pass:
    `test_pass_when_todos_empty` failed whenever
    `TAB_BOOKMAKER_CONFIRMED=false` (the default) because it did not control
    the runtime TODO appended by `_check_critical_todos`.
- `ruff check .` — 202 findings (style/modernization: `datetime.UTC` aliases,
  unused imports, import order, line length). Not CI-gated (no CI is
  configured), none identified as correctness defects. Known style debt.
  *(Historical record. "Not CI-gated" was closed by PR #3, merge commit
  `c3bee0c`; current counts are in the 2026-10-15 section below.)*
- No type-check gate is configured to run in CI; `mypy` config exists in
  `pyproject.toml` (non-strict).

## Full validation baseline (2026-10-15)

Measured on Windows 11 with Python 3.11.9 in a fresh venv built from
`requirements-dev.txt` (ruff 0.17.0, pytest 9.1.1, pydantic 2.14.1,
starlette 1.8.0, fastapi 0.143.1), using the env CI sets
(`APP_ENV=development API_SECRET_KEY=ci-test-secret DB_URL=sqlite:///:memory:
MPLBACKEND=Agg`). "main" = `c3bee0c` (PR #3 merged); "branch" = the lint
cleanup PR that adds this section. GitHub CI results for the branch are on
its PR, not restated here.

### CI split (from `.github/workflows/ci.yml` as merged in #3)

- `tests` job: `python -m pytest tests/ -q` on Python 3.11 — blocking.
- `lint` job, blocking: `python -m ruff check . --ignore
  E501,E712,E741,F401,F841,I001,UP007,UP017,UP035,UP037` — gates every
  selected (`E`, `F`, `I`, `UP`) rule that had zero findings at the #3 /
  main `c3bee0c` baseline. On this branch UP017 and F401 also reach zero but
  stay in the ignore list until the follow-up below.
- `lint` job, non-blocking: `python -m ruff check . --exit-zero --statistics`
  — full debt report in the job summary.

### Ruff 0.17.0 — before/after by code

Commands: `python -m ruff check . --exit-zero --statistics` (totals) and
`python -m ruff check . --select <CODE>` (per-code zero check).

| Code | main | branch | Notes |
|---|---:|---:|---|
| UP017 datetime-timezone-utc | 62 | **0** | fixed (`timezone.utc` → `UTC`) |
| F401 unused-import | 41 | **0** | fixed; see side-effect note below |
| E501 line-too-long | 38 | 38 | out of mechanical scope |
| I001 unsorted-imports | 29 | 3 | 3 remain in deliberately excluded files |
| UP007 non-pep604-annotation-union | 12 | 12 | out of scope (modernization) |
| UP035 deprecated-import | 7 | 7 | out of scope (modernization) |
| F841 unused-variable | 5 | 5 | out of scope (removal touches statements) |
| E712 true-false-comparison | 4 | 4 | out of scope (`tests/test_simulation.py` asserts on pandas/numpy values; rewriting changes assertion semantics) |
| UP037 quoted-annotation | 3 | 3 | out of scope (modernization) |
| E741 ambiguous-variable-name | 1 | 1 | out of scope (rename) |
| **Total** | **202** | **73** | blocking command passes on both |

Remaining I001 (excluded on purpose, unchanged):
- `models/ensemble.py` — model code is outside this cleanup's ownership.
- `db/models/__init__.py` — documents "Order matters" for model registration.
- `db/migrations/env.py` — the sort would separate the `import db.models`
  registration import from its explanatory comment block.

Only Ruff's safe fixes were applied (no `--unsafe-fixes`), to an explicit
file list. Excluded from editing: `models/**`,
`orchestration/jobs/train_models.py`,
`orchestration/jobs/generate_recommendations.py`, `api/routes/fixtures.py`,
`tests/test_fixtures_config.py`, plus the two `db` files above. One removed
F401 looks like a registration import: `DailyPipelineRun` in
`tests/test_live_readiness.py`. It is redundant because `db/models/__init__.py`
imports it whenever any `db.models.*` module is imported.

Follow-up (not done here; `ci.yml` is owned by the CI PR and needs separate
authorization): **UP017 and F401 are now at 0** and can be removed from the
blocking `--ignore` list and the inline debt comment in `ci.yml`.

### pytest

| Tree | Result |
|---|---|
| main `c3bee0c` | 314 passed, 1 skipped, 3 warnings |
| branch | 314 passed, 1 skipped, 3 warnings (no change) |

314 = the historical 313 plus the backtest-summary ensemble-weights contract
test (commit `36d1669`). The skip is the same by-design skip as 2026-08-25
(`tests/test_live_readiness.py:232`, no critical TODOs defined). Warnings, identical
on both trees:
1. `PydanticDeprecatedSince20` — class-based `config` in
   `api/routes/fixtures.py:12`. Addressed by PR #2 (OPEN at `7d56af8` when
   this was written; it reports 317 passed, 1 skipped, 1 warning on its branch).
2. `PydanticDeprecatedSince211` — instance access to `model_fields` at
   `tests/test_dashboard_contract.py:146`. Not covered by any open PR; outside
   mechanical lint scope. Open item.
3. `StarletteDeprecationWarning` — `httpx` with `starlette.testclient`, raised
   from the installed fastapi/starlette versions, not repository code. It
   depends on the resolved package versions, which is why other environments
   (e.g. a Python 3.12.10 env reporting 2 warnings) can count differently.

Related open PR: README on main `c3bee0c` still says "Ruff is a separate
local check", which is stale since #3. #4 (OPEN, pending, at `53c1993`)
removes that sentence; this PR does not touch README.

## Issues found and fixed in this pass

1. Readiness test/env coupling (above).
2. Ensemble weight double definition: `config/settings.py` declared
   bookmaker/elo/xgboost/poisson weights that only fed the dashboard display,
   while the production ensemble used a different hardcoded dict in
   `generate_recommendations.py`. The dashboard therefore displayed weights
   (including a bookmaker component) that the ensemble did not use. Weights
   are now single-sourced from settings.
3. Accidental artifacts removed from version control: `=0.14`, `=0.44`,
   `=2.0` (pip output captured by unquoted `>=` specifiers in PowerShell) and
   a root `settings.json` (local tool permissions file).

Found by the independent (Codex) review of this pass and fixed:

4. CLV sign inversion: `settle_results._compute_clv` persisted
   `(1/bet_odds) − (1/closing_odds)` — the opposite of the documented
   convention in `evaluation/clv_tracker.py` (positive = beat the close) —
   so per-bet CLV shown by the dashboard/Discord history had inverted sign.
   Now aligned with the canonical convention. (Aggregate CLV summaries were
   unaffected — they recompute via `clv_tracker`.) Note for operators: the
   fix corrects future writes only — `BetOutcome.clv` rows already settled
   in an existing operator database carry the old (inverted) sign and need
   recomputation before per-bet CLV history can be compared across the fix.
5. Weather look-ahead disclosure: historical `weather_*` features come from
   Open-Meteo *archive* observations at kickoff, not pre-match forecasts —
   post-bet-time information. Documented in `docs/backtesting.md` ("Known
   deviation"), the extractor docstring, README, and PORTFOLIO_FACTS; the
   code path itself is unchanged (fixing it needs forecast-issued-at
   snapshots and is future work).
6. Doc-accuracy corrections: `docs/planning/ACCURACY_PLAN.md` marked as a historical
   planning document (its "missing" items have since been implemented), and
   README/PORTFOLIO_FACTS wording corrected so the backtest is described as
   evaluating individual models (the calibrated ensemble used in production
   is not yet covered by the backtest runner).
7. Added a contract test for `/api/dashboard/backtest-summary` ensemble
   weights (previously uncovered).

## Generated artifacts policy (unchanged)

`logs/**`, `reviews/**`, `storage/daily_summaries/**`, and
`storage/model_artifacts/*.json` are operational/review evidence, kept
deliberately. They are historical records and should not be edited to
"improve" results.

## Not verifiable locally — standing limitations

- **No performance claim in this repository is independently reproducible from
  the repository contents alone.** Regenerating metrics requires re-ingesting
  data from external APIs (Squiggle, The Odds API, Open-Meteo, AFL Tables).
- The bookmaker-baseline figures recorded in `docs/planning/ACCURACY_PLAN.md` were computed
  when odds coverage in training data was ~0%, so they are not a valid market
  comparison; the repository makes **no claim of beating bookmaker prices**.
- The paper-trading log (`storage/paper_trading_log.md`) contains no entries:
  there are **zero recorded paper-trading results**.
- The live-readiness gate correctly evaluates to `not_ready`.
