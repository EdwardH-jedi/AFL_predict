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
  *(Historical record. "Not CI-gated" was closed by PR #3 (`c3bee0c`), and
  #6 (`eeaa5e9`) cleared everything except E501; current counts are in the
  2026-10-15 section below.)*
- No type-check gate is configured to run in CI; `mypy` config exists in
  `pyproject.toml` (non-strict).

## Full validation baseline (2026-10-15)

Measured on Windows 11 with Python 3.11.9 in a fresh venv built from
`requirements-dev.txt` (ruff 0.17.0, pytest 9.1.1, pydantic 2.14.1,
starlette 1.8.0, fastapi 0.143.1), using the env CI sets
(`APP_ENV=development API_SECRET_KEY=ci-test-secret DB_URL=sqlite:///:memory:
MPLBACKEND=Agg`). "main" = `28ec2f4` (#6 and #4 merged; #4 changed only
README and `.gitignore`, so code/test counts equal `eeaa5e9`). This section is
a docs-only change; code, tests and `ci.yml` are identical to main, so every
count below is main's. Ruff config (`pyproject.toml`) and the ruff pin were
unchanged between `c3bee0c` and `28ec2f4`, so the Ruff columns are comparable.

### CI split (`.github/workflows/ci.yml` at main `28ec2f4`, unchanged since #6)

- `tests` job: `python -m pytest tests/ -q` on Python 3.11 — blocking.
- `lint` job, blocking: `python -m ruff check . --ignore E501` — every
  selected (`E`, `F`, `I`, `UP`) rule except E501 is gated.
- `lint` job, non-blocking: `python -m ruff check . --exit-zero --statistics`
  — full debt report in the job summary.

### Ruff 0.17.0 by code

Command: `python -m ruff check . --exit-zero --statistics`.

| Code | `c3bee0c` (after #3) | `28ec2f4` (after #6, #4) |
|---|---:|---:|
| UP017 datetime-timezone-utc | 62 | 0 |
| F401 unused-import | 41 | 0 |
| E501 line-too-long | 38 | **38** |
| I001 unsorted-imports | 29 | 0 |
| UP007 non-pep604-annotation-union | 12 | 0 |
| UP035 deprecated-import | 7 | 0 |
| F841 unused-variable | 5 | 0 |
| E712 true-false-comparison | 4 | 0 |
| UP037 quoted-annotation | 3 | 0 |
| E741 ambiguous-variable-name | 1 | 0 |
| **Total** | **202** | **38** |

The cleanup was done by #6. An earlier revision of PR #5 cleared
UP017/F401/I001 only (202 → 73 at `c3bee0c`); #6 superseded it.

E501 is 38, not the 37 in the `ci.yml` comment and #6's description. #6
measured 37 at its first commit `d414155`; its later commit `916d8b8` added
`tests/test_quant_dashboard_static.py:45` (103 > 100). Main CI run
38709210297 also reports "Found 38 errors". The `ci.yml` comment is one
stale; correcting it belongs to the `ci.yml` owner.

### pytest

| Tree | Result |
|---|---|
| main `c3bee0c` (after #3) | 314 passed, 1 skipped, 3 warnings |
| main `eeaa5e9` (after #6) | 315 passed, 1 skipped, 3 warnings |
| main `28ec2f4` (after #4) | **315 passed, 1 skipped, 3 warnings** |

315 = the historical 313, plus the backtest-summary ensemble-weights contract
test (`36d1669`), plus #6's
`test_quant_dashboard_badge_distinguishes_demo_mixed_live`. The skip is the
same by-design skip as 2026-08-25 (`tests/test_live_readiness.py:232`, no
critical TODOs defined). Warnings:
1. `PydanticDeprecatedSince20` — class-based `config` in
   `api/routes/fixtures.py:12`. Addressed by PR #2 (OPEN, pending, at
   `85d2bcf` when this was written).
2. `PydanticDeprecatedSince211` — instance access to `model_fields` at
   `tests/test_dashboard_contract.py:146`. Not covered by any open PR. Open
   item.
3. `StarletteDeprecationWarning` — `httpx` with `starlette.testclient`, raised
   from the installed fastapi/starlette versions, not repository code. It
   depends on the resolved package versions, so other environments can count
   differently (a Python 3.12.10 env reported 2 warnings).

README at main `28ec2f4` (after #4 merged) describes the Ruff CI gate in
"Tests and verification", but its stack table still says "local Ruff tooling;
current CI runs the Python regression suite". #4 did not change that row and
no open PR covers it. Open item.

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
